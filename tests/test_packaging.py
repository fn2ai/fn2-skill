"""Cross-harness packaging and local-install smoke tests."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "fn2"

sys.path.insert(0, str(SKILL / "scripts"))
from fn2cli import __version__  # noqa: E402  (after sys.path setup)
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
            "references/research.md",
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

    def test_skill_description_triggers_on_earnings_and_fits_the_limit(self):
        """The description is what makes an assistant load the skill at all.

        An earnings or financial-data question has to match it, and the Agent
        Skills format caps a description at 1024 characters.
        """
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        block = re.search(r"description: >\n(.*?)\n\S", frontmatter, re.S)
        self.assertIsNotNone(block)
        description = " ".join(line.strip() for line in block.group(1).splitlines())
        self.assertLessEqual(len(description), 1024, len(description))
        lead = description[:300].lower()  # listings truncate: the trigger goes first
        for phrase in ("earnings", "financial"):
            self.assertIn(phrase, lead)
        for phrase in ("consensus", "transcripts", "agents", "schedule"):
            self.assertIn(phrase, description.lower())

    def test_documented_research_commands_exist_and_parse(self):
        """Every research command line the docs show must be one the CLI accepts.

        `SKILL.md` is a prompt: an assistant runs these lines as written, so a
        renamed flag here is a broken instruction, not a typo.
        """
        from fn2cli import cli

        verbs = ("earnings", "calls", "transcript", "search", "financials",
                 "price", "fred", "recall")
        parser = cli.build_parser()
        transcript_id = "0f8b2c1e-5d4a-4b7c-9e21-3a6f8d1c2b40"
        sources = {
            "SKILL.md": (SKILL / "SKILL.md", 'python3 "$FN2" '),
            "references/research.md": (SKILL / "references" / "research.md",
                                       'python3 "$FN2" '),
            "README.md": (ROOT / "README.md", "fn2 "),
        }
        for name, (path, prefix) in sources.items():
            seen = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.startswith(prefix):
                    continue
                command = line[len(prefix):]
                if not command.split() or command.split()[0] not in verbs:
                    continue
                # Placeholders such as `<id>` or `<row 1 id>` stand for a
                # transcript id; a trailing `# …` is the doc's own comment.
                command = re.sub(r"<[^>]*>", transcript_id, command)
                argv = shlex.split(command, comments=True)
                with self.subTest(doc=name, command=line.strip()):
                    args = parser.parse_args(argv)  # SystemExit = a doc bug
                    self.assertTrue(callable(args.func))
                seen.add(argv[0])
            self.assertTrue(seen, f"{name} shows no research command")
            if name != "references/research.md":  # its table lists them all
                self.assertEqual(seen, set(verbs),
                                 f"{name} does not show every research command")
        reference = sources["references/research.md"][0].read_text(encoding="utf-8")
        for verb in verbs:
            self.assertIn(f"| `{verb} ", reference.replace("[", " "), verb)

    def test_references_document_every_research_route(self):
        api_md = (SKILL / "references" / "api.md").read_text(encoding="utf-8")
        for route in ("/research/earnings", "/research/transcripts",
                      "/research/transcripts/read",
                      "/research/transcripts/search", "/research/financials",
                      "/research/prices", "/research/fred", "/research/recall"):
            self.assertIn(f"`{route}`", api_md, route)
        self.assertIn('"scopes": ["agents", "models", "research"]', api_md)
        trouble = (SKILL / "references" / "troubleshooting.md").read_text(
            encoding="utf-8")
        self.assertIn("Missing scope: research", trouble)
        self.assertIn("api_quota_exceeded", trouble)

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
                "PI_CODING_AGENT_DIR": str(home / ".pi" / "agent"),
            })
            subprocess.run(
                ["make", "install"], cwd=ROOT, env=env,
                check=True, text=True, capture_output=True)

            links = (
                home / ".claude" / "skills" / "fn2",
                home / ".codex" / "skills" / "fn2",
                home / ".pi" / "agent" / "skills" / "fn2",
            )
            for link in links:
                self.assertTrue(link.is_symlink(), link)
                self.assertEqual(link.resolve(), SKILL.resolve())
                version = subprocess.run(
                    [sys.executable, str(link / "scripts" / "fn2"), "--version"],
                    check=True, text=True, capture_output=True).stdout.strip()
                self.assertEqual(version, f"fn2-skill {__version__}")

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
            "pi": ".pi/agent/skills/fn2",
            "legacy Hermes location": ".hermes/skills/fn2",
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
                            "PI_CODING_AGENT_DIR": str(home / ".pi" / "agent"),
                        }
                        # An empty cwd: the `$(pwd)` fallback must not rescue us.
                        result = subprocess.run(
                            ["bash", "-c", snippet, "fn2", "--version"],
                            env=env, cwd=temp, text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn(marker, result.stdout)

    def test_pi_custom_agent_directory_installs_and_resolves_without_touching_hermes(self):
        from fn2cli import cli

        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp) / "home"
            agent_dir = home / "custom-pi"
            hermes = home / ".hermes" / "skills" / "fn2"
            hermes.mkdir(parents=True)
            marker = hermes / "keep-me"
            marker.write_text("independent Hermes installation", encoding="utf-8")
            env = {
                "HOME": str(home),
                "PATH": os.environ.get("PATH", ""),
                "PI_CODING_AGENT_DIR": str(agent_dir),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                "CODEX_HOME": str(home / ".codex"),
            }
            subprocess.run(["make", "install-pi"], cwd=ROOT, env=env,
                           check=True, text=True, capture_output=True)
            installed = agent_dir / "skills" / "fn2"
            self.assertEqual(installed.resolve(), SKILL.resolve())
            for snippet, expected in (
                (_bash_block(SKILL / "SKILL.md", "## Locating the helper"), "usage: fn2"),
                (cli._LAUNCHER + "\n", f"fn2-skill {__version__}"),
            ):
                result = subprocess.run(
                    ["bash", "-c", snippet, "fn2", "--version"],
                    cwd=temp, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
            subprocess.run(["make", "uninstall"], cwd=ROOT, env=env,
                           check=True, text=True, capture_output=True)
            self.assertFalse(installed.is_symlink())
            self.assertEqual(marker.read_text(), "independent Hermes installation")

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
