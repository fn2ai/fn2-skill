"""Cross-harness packaging and local-install smoke tests."""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "fn2"
REPOSITORY = "https://github.com/fn2ai/fn2-skill"


def _json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


class PackagingTests(unittest.TestCase):
    def test_canonical_skill_bundle_is_complete(self):
        for relative in (
            "SKILL.md",
            "agents/openai.yaml",
            "scripts/fn2",
            "scripts/fn2cli/cli.py",
            "references/api.md",
            "references/scheduling.md",
            "references/troubleshooting.md",
        ):
            self.assertTrue((SKILL / relative).is_file(), relative)

    def test_manifests_share_name_version_and_skill_directory(self):
        codex = _json(ROOT / ".codex-plugin" / "plugin.json")
        claude = _json(ROOT / ".claude-plugin" / "plugin.json")
        self.assertEqual(codex["name"], "fn2")
        self.assertEqual(claude["name"], "fn2")
        self.assertEqual(codex["version"], claude["version"])
        self.assertEqual(codex["skills"], "./skills/")
        self.assertEqual(claude["skills"], "./skills/")
        self.assertEqual(codex["repository"], REPOSITORY)
        self.assertEqual(claude["repository"], REPOSITORY)

        init_py = (SKILL / "scripts" / "fn2cli" / "__init__.py").read_text()
        cli_version = re.search(r'^__version__ = "([^"]+)"$', init_py, re.MULTILINE)
        self.assertIsNotNone(cli_version)
        self.assertEqual(codex["version"], cli_version.group(1))

    def test_skill_frontmatter_is_accepted_by_codex_and_claude(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        self.assertIn("name: fn2", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertIn("allowed-tools: Bash", frontmatter)
        self.assertNotRegex(frontmatter, r"(?m)^version:")
        self.assertNotRegex(frontmatter, r"(?m)^platforms:")

    def test_marketplaces_reference_the_upstream_plugin(self):
        codex = _json(ROOT / ".agents" / "plugins" / "marketplace.json")
        claude = _json(ROOT / ".claude-plugin" / "marketplace.json")
        self.assertEqual(codex["name"], "fn2")
        self.assertEqual(claude["name"], "fn2")
        self.assertEqual(claude["owner"]["name"], "fn2")
        self.assertEqual(codex["plugins"][0]["source"]["url"], REPOSITORY + ".git")
        self.assertEqual(claude["plugins"][0]["source"]["repo"], "fn2ai/fn2-skill")

    def test_make_install_links_the_same_bundle_for_every_harness(self):
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp)
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                "CODEX_HOME": str(home / ".codex"),
                "HERMES_HOME": str(home / ".hermes"),
            })
            subprocess.run(
                ["make", "install"], cwd=ROOT, env=env,
                check=True, text=True, capture_output=True)

            links = (
                home / ".claude" / "skills" / "fn2",
                home / ".codex" / "skills" / "fn2",
                home / ".hermes" / "skills" / "fn2",
            )
            for link in links:
                self.assertTrue(link.is_symlink(), link)
                self.assertEqual(link.resolve(), SKILL.resolve())
                version = subprocess.run(
                    [sys.executable, str(link / "scripts" / "fn2"), "--version"],
                    check=True, text=True, capture_output=True).stdout.strip()
                self.assertEqual(version, "fn2-skill 0.3.0")

            subprocess.run(
                ["make", "uninstall"], cwd=ROOT, env=env,
                check=True, text=True, capture_output=True)
            for link in links:
                self.assertFalse(link.is_symlink(), link)

    def test_make_install_refuses_to_replace_a_real_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp)
            existing = home / ".claude" / "skills" / "fn2"
            existing.mkdir(parents=True)
            marker = existing / "keep-me"
            marker.write_text("owned by the user", encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            })
            result = subprocess.run(
                ["make", "install-claude"], cwd=ROOT, env=env,
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(marker.is_file())


if __name__ == "__main__":
    unittest.main()
