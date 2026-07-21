# fn2 skill — no build step; these targets just verify and link the skill.

SKILL_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PYTHON ?= python3

CLAUDE_SKILLS := $(HOME)/.claude/skills
CODEX_HOME := $(if $(CODEX_HOME),$(CODEX_HOME),$(HOME)/.codex)
HERMES_HOME := $(if $(HERMES_HOME),$(HERMES_HOME),$(HOME)/.hermes)

.PHONY: help test lint install install-claude install-codex install-pi uninstall

help:
	@echo "fn2 skill targets:"
	@echo "  make test      run the unit tests (no network)"
	@echo "  make lint      byte-compile every module"
	@echo "  make install   symlink into detected harnesses (Claude / Codex / Pi)"
	@echo "  make uninstall remove those symlinks"

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m py_compile scripts/fn2 scripts/fn2cli/*.py
	@echo "ok — all modules compile"

install: install-claude install-codex install-pi
	@echo "done."

install-claude:
	@mkdir -p "$(CLAUDE_SKILLS)"
	@ln -sfn "$(SKILL_DIR)" "$(CLAUDE_SKILLS)/fn2" && echo "linked Claude → $(CLAUDE_SKILLS)/fn2"

install-codex:
	@mkdir -p "$(CODEX_HOME)/plugins"
	@ln -sfn "$(SKILL_DIR)" "$(CODEX_HOME)/plugins/fn2" && echo "linked Codex  → $(CODEX_HOME)/plugins/fn2"

install-pi:
	@mkdir -p "$(HERMES_HOME)/skills"
	@ln -sfn "$(SKILL_DIR)" "$(HERMES_HOME)/skills/fn2" && echo "linked Pi     → $(HERMES_HOME)/skills/fn2"

uninstall:
	@rm -f "$(CLAUDE_SKILLS)/fn2" "$(CODEX_HOME)/plugins/fn2" "$(HERMES_HOME)/skills/fn2"
	@echo "removed skill symlinks (stored credentials untouched)."
