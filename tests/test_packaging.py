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


def _bash_block(path: pathlib.Path, heading: str) -> str:
    """The first ```bash fence under `heading`, so tests run the documented text."""
    body = path.read_text(encoding="utf-8").split(heading, 1)[1]
    return body.split("```bash", 1)[1].split("```", 1)[0]


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
                self.assertEqual(version, "fn2-skill 0.5.0")

            subprocess.run(
                ["make", "uninstall"], cwd=ROOT, env=env,
                check=True, text=True, capture_output=True)
            for link in links:
                self.assertFalse(link.is_symlink(), link)

    def test_documented_shell_snippets_find_every_install_layout(self):
        """The resolution chain in SKILL.md and the launcher `fn2 link` writes
        must both find the helper, whichever way it was installed.

        A marketplace install lands in a versioned directory that moves on
        every update, so this is exactly the case a hardcoded path gets wrong.
        """
        sys.path.insert(0, str(SKILL / "scripts"))
        from fn2cli import cli  # noqa: E402  (path set above)

        # (script, marker its output must contain once it resolved the helper)
        snippets = {
            "SKILL.md": (_bash_block(SKILL / "SKILL.md", "## Locating the helper"),
                         "usage: fn2"),
            "fn2 link launcher": (cli._LAUNCHER + "\n", "fn2-skill"),
        }
        layouts = {
            # `claude plugin install`: cache/<marketplace>/<plugin>/<version>/
            "plugin cache": ".claude/plugins/cache/fn2/fn2/9.9.9/skills/fn2",
            "make install": ".claude/skills/fn2",
            "codex": ".codex/skills/fn2",
            "pi": ".hermes/skills/fn2",
        }
        for source, (snippet, marker) in snippets.items():
            for name, relative in layouts.items():
                with self.subTest(snippet=source, layout=name):
                    with tempfile.TemporaryDirectory() as temp:
                        home = pathlib.Path(temp) / "home"
                        target = home / relative
                        target.parent.mkdir(parents=True)
                        os.symlink(SKILL, target)
                        env = {
                            "HOME": str(home),
                            "PATH": os.environ.get("PATH", ""),
                            # A relocated Claude home must still resolve.
                            "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                            "CODEX_HOME": str(home / ".codex"),
                            "HERMES_HOME": str(home / ".hermes"),
                        }
                        # An empty cwd: the `$(pwd)` fallback must not rescue us.
                        result = subprocess.run(
                            ["bash", "-c", snippet, "fn2", "--version"],
                            env=env, cwd=temp, text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn(marker, result.stdout)

    def test_readme_does_not_promise_an_fn2_binary_before_defining_one(self):
        """`claude plugin install` adds no PATH entry, so the README must not
        hand the reader a `fn2 …` command before it says how to get one.

        Only fenced shell blocks count: prose and image alt text may name the
        command while describing it.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        caveat = readme.index("nothing lands on your `PATH`")
        offset, linked = 0, False
        for block in re.findall(r"```bash\n(.*?)```", readme, re.S):
            start = readme.index(block, offset)
            offset = start + len(block)
            if "scripts/fn2 link" in block:
                linked = True
                self.assertLess(caveat, start,
                                "the PATH caveat must come before `fn2 link`")
                continue
            runs_fn2 = [line for line in block.splitlines()
                        if line.strip().startswith("fn2 ")]
            if runs_fn2:
                self.assertTrue(
                    linked,
                    f"README runs {runs_fn2[0].strip()!r} before `fn2 link`")

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
