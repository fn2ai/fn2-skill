# fn2 skill — no build step; these targets verify and link the skill.

PLUGIN_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SKILL_DIR := $(PLUGIN_DIR)/skills/fn2
PYTHON ?= python3

CLAUDE_CONFIG_DIR ?= $(HOME)/.claude
CODEX_HOME ?= $(HOME)/.codex
PI_CODING_AGENT_DIR ?= $(HOME)/.pi/agent

CLAUDE_SKILLS := $(CLAUDE_CONFIG_DIR)/skills
CODEX_SKILLS := $(CODEX_HOME)/skills

.PHONY: help test lint validate media install install-claude install-codex install-pi uninstall

help:
	@echo "fn2 skill targets:"
	@echo "  make test      run the unit tests (no network)"
	@echo "  make lint      byte-compile every module"
	@echo "  make validate  validate the Claude plugin when Claude Code is installed"
	@echo "  make media     regenerate docs/media (needs Chromium + ImageMagick)"
	@echo "  make install   symlink into detected harnesses (Claude / Codex / Pi)"
	@echo "  make uninstall remove those symlinks"

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m py_compile skills/fn2/scripts/fn2 skills/fn2/scripts/fn2cli/*.py
	@echo "ok — all modules compile"

validate:
	@if command -v claude >/dev/null 2>&1; then \
		claude plugin validate --strict "$(PLUGIN_DIR)/.claude-plugin/plugin.json" && \
		claude plugin validate --strict "$(PLUGIN_DIR)/.claude-plugin/marketplace.json"; \
	else \
		echo "skip — Claude Code is not installed"; \
	fi

media:
	$(PYTHON) tools/screenshots/generate.py

install: install-claude install-codex install-pi
	@echo "done."
	@echo
	@echo "note: nothing was added to PATH. Your assistant runs the helper for you."
	@echo "      To drive it from a shell, add this to your shell rc:"
	@echo
	@echo "        alias fn2='python3 $(SKILL_DIR)/scripts/fn2'"

install-claude:
	@mkdir -p "$(CLAUDE_SKILLS)"
	@test ! -e "$(CLAUDE_SKILLS)/fn2" || test -L "$(CLAUDE_SKILLS)/fn2" || \
		{ echo "error: $(CLAUDE_SKILLS)/fn2 exists and is not a symlink" >&2; exit 1; }
	@ln -sfn "$(SKILL_DIR)" "$(CLAUDE_SKILLS)/fn2" && echo "linked Claude → $(CLAUDE_SKILLS)/fn2"

install-codex:
	@mkdir -p "$(CODEX_SKILLS)"
	@test ! -e "$(CODEX_SKILLS)/fn2" || test -L "$(CODEX_SKILLS)/fn2" || \
		{ echo "error: $(CODEX_SKILLS)/fn2 exists and is not a symlink" >&2; exit 1; }
	@ln -sfn "$(SKILL_DIR)" "$(CODEX_SKILLS)/fn2" && echo "linked Codex  → $(CODEX_SKILLS)/fn2"

install-pi:
	@mkdir -p "$(PI_CODING_AGENT_DIR)/skills"
	@test ! -e "$(PI_CODING_AGENT_DIR)/skills/fn2" || test -L "$(PI_CODING_AGENT_DIR)/skills/fn2" || \
		{ echo "error: $(PI_CODING_AGENT_DIR)/skills/fn2 exists and is not a symlink" >&2; exit 1; }
	@ln -sfn "$(SKILL_DIR)" "$(PI_CODING_AGENT_DIR)/skills/fn2" && echo "linked Pi     → $(PI_CODING_AGENT_DIR)/skills/fn2"

uninstall:
	@for path in "$(CLAUDE_SKILLS)/fn2" "$(CODEX_SKILLS)/fn2" "$(PI_CODING_AGENT_DIR)/skills/fn2"; do \
		if test -L "$$path"; then rm "$$path"; fi; \
	done
	@echo "removed skill symlinks (stored credentials untouched)."
