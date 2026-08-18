SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ifndef VENV_DIR
  VENV_DIR := $(HOME)/.venvs/chordflask
  ifeq ($(wildcard $(VENV_DIR)/bin/python),)
    ifneq ($(wildcard $(HOME)/.venvs/chordifier/bin/python),)
      VENV_DIR := $(HOME)/.venvs/chordifier
    endif
  endif
endif
VENV_PYTHON := $(VENV_DIR)/bin/python
PYTHON_BIN ?=
TEST_ARGS ?=
ANALYZE_ARGS ?=
DEMUCS_ARGS ?=
EXPORT_ARGS ?=
MAINTAIN_ARGS ?=
EXTRA_TEST_DIRS ?=
EXTRA_SRC_DIRS ?=
EXTRA_PYTHONPATH ?=

-include $(ROOT_DIR)/.extra-checks.mk

.PHONY: help all install setup setup-runtime setup-dev setup-recreate \
	fix-permissions test check lint run worker standalone standalone-run \
	plugins analyze demucs export maintain setup-btc btc-check setup-demucs \
	demucs-check status clean clean-report

help:
	@printf '%s\n' \
		'ChordFlask commands' \
		'' \
		'  make                     Show this help (no changes)' \
		'  make all                 Full idempotent setup: permissions, venv, tests, checks' \
		'  make setup               Full contributor setup: runtime and test tools [installs]' \
		'  make install             Alias for make setup [installs]' \
		'  make setup-runtime       Runtime-only virtual environment [installs]' \
		'  make setup-dev           Alias for make setup [installs]' \
		'  make setup-recreate      Delete and recreate the full venv [destructive]' \
		'  make fix-permissions     Restore executable bits lost by Nextcloud sync' \
		'  make test                Run the test suite' \
		'  make check               Run tests, lint, compile checks, and git diff checks' \
		'  make run                 Start the worker and web app' \
		'  make worker              Start only the analysis worker' \
		'  make analyze             Analyze media (chordflask-analyze)' \
		'  make demucs              Create Demucs FLAC stem sets (optional runtime)' \
		'  make export              Export leadsheets (chordflask-export)' \
		'  make maintain            Maintain data/installation (chordflask-maintain)' \
		'  make setup-btc           Set up the optional BTC analyzer runtime [installs]' \
		'  make btc-check           Diagnose the optional BTC analyzer runtime' \
		'  make setup-demucs        Set up the optional Demucs runtime [installs]' \
		'  make demucs-check        Diagnose the optional Demucs runtime' \
		'  make standalone          Check, build, and package the standalone release [long]' \
		'  make standalone-run      Start an already-built standalone release' \
		'  make plugins             Install Vamp plugins into the user plugin directory [network]' \
		'  make status              Show Git status (read-only)' \
		'  make clean               Remove build output and developer caches [destructive]' \
		'  make clean-report        Show reclaimable space without deleting anything' \
		$(EXTRA_HELP_ARGS) \
		'' \
		'Variables:' \
		'  VENV_DIR=/path           Virtual environment (default: ~/.venvs/chordflask)' \
		'  PYTHON_BIN=python3.12     Interpreter used to create a virtual environment' \
		'  TEST_ARGS="-q -k name"    Additional pytest arguments' \
		'  DEMUCS_ARGS="--dry-run videos"  Arguments for make demucs' \
		'  CHORDIFIER_PORT=5050      Port used by make run' \
		'' \
		'Examples:' \
		'  make all' \
		'  make test TEST_ARGS="-q"' \
		'  CHORDIFIER_PORT=5050 make run' \
		''

all: fix-permissions setup check

fix-permissions:
	@bash "$(ROOT_DIR)/scripts/fix_permissions.sh"

setup:
	@CHORDFLASK_VENV="$(VENV_DIR)" CHORDIFIER_PYTHON="$(PYTHON_BIN)" \
		bash "$(ROOT_DIR)/scripts/setup_venv.sh" --dev

install: setup

setup-runtime:
	@CHORDFLASK_VENV="$(VENV_DIR)" CHORDIFIER_PYTHON="$(PYTHON_BIN)" \
		bash "$(ROOT_DIR)/scripts/setup_venv.sh"

setup-dev: setup

setup-recreate:
	@CHORDFLASK_VENV="$(VENV_DIR)" CHORDIFIER_PYTHON="$(PYTHON_BIN)" \
		bash "$(ROOT_DIR)/scripts/setup_venv.sh" --dev --recreate

test:
	@PYTHONPATH="$(EXTRA_PYTHONPATH)" CHORDFLASK_VENV="$(VENV_DIR)" \
		bash "$(ROOT_DIR)/scripts/run_tests.sh" \
		"$(ROOT_DIR)/tests" $(EXTRA_TEST_DIRS) $(TEST_ARGS)

check: test lint
	@"$(VENV_PYTHON)" -m compileall -q "$(ROOT_DIR)/flask" "$(ROOT_DIR)/scripts" \
		"$(ROOT_DIR)/tests" "$(ROOT_DIR)/chordflask_base" "$(ROOT_DIR)/chordflask_maintain" \
		"$(ROOT_DIR)/chordflask_btc" "$(ROOT_DIR)/chordflask_demucs" $(EXTRA_SRC_DIRS)
	@git -C "$(ROOT_DIR)" diff --check

lint:
	@"$(VENV_PYTHON)" -m ruff check "$(ROOT_DIR)/flask" "$(ROOT_DIR)/tests" \
		"$(ROOT_DIR)/scripts" "$(ROOT_DIR)/chordflask_base" "$(ROOT_DIR)/chordflask_maintain" \
		"$(ROOT_DIR)/chordflask_btc" "$(ROOT_DIR)/chordflask_demucs" $(EXTRA_SRC_DIRS) $(EXTRA_TEST_DIRS)

run:
	@cd "$(ROOT_DIR)" && PYTHON_BIN="$(VENV_PYTHON)" bash scripts/chordflask.sh

worker:
	@cd "$(ROOT_DIR)/flask" && PYTHONPATH="$(ROOT_DIR)$${PYTHONPATH:+:$${PYTHONPATH}}" "$(VENV_PYTHON)" chordflask.py --worker

analyze:
	@CHORDFLASK_VENV="$(VENV_DIR)" bash "$(ROOT_DIR)/scripts/chordflask-analyze" $(ANALYZE_ARGS)

demucs:
	@CHORDFLASK_VENV="$(VENV_DIR)" bash "$(ROOT_DIR)/scripts/chordflask-demucs" $(DEMUCS_ARGS)

export:
	@CHORDFLASK_VENV="$(VENV_DIR)" bash "$(ROOT_DIR)/scripts/chordflask-export" $(EXPORT_ARGS)

maintain:
	@CHORDFLASK_VENV="$(VENV_DIR)" bash "$(ROOT_DIR)/scripts/chordflask-maintain" $(MAINTAIN_ARGS)

setup-btc:
	@bash "$(ROOT_DIR)/scripts/setup-btc.sh"

btc-check:
	@bash "$(ROOT_DIR)/scripts/btc-check.sh"

setup-demucs:
	@bash "$(ROOT_DIR)/scripts/setup-demucs.sh"

demucs-check:
	@bash "$(ROOT_DIR)/scripts/demucs-check.sh"

standalone: check
	@PATH="$(VENV_DIR)/bin:$$PATH" bash "$(ROOT_DIR)/flask/build_standalone.sh"

standalone-run:
	@release_name=$$(cat "$(ROOT_DIR)/flask/dist/.latest-release" 2>/dev/null || true); \
	launcher="$(ROOT_DIR)/flask/dist/$${release_name}/chordflask.sh"; \
	if [[ -z "$${release_name}" || ! -x "$${launcher}" ]]; then \
		echo 'Standalone build not found. Run: make standalone' >&2; \
		exit 1; \
	fi; \
	cd "$(ROOT_DIR)" && "$${launcher}"

plugins:
	@CHORDFLASK_VENV="$(VENV_DIR)" bash "$(ROOT_DIR)/flask/install_vamp.sh"

status:
	@git -C "$(ROOT_DIR)" status --short

clean:
	@echo 'Removing standalone build output and developer caches.'
	@rm -rf \
		"$(ROOT_DIR)/flask/build" \
		"$(ROOT_DIR)/flask/dist" \
		"$(ROOT_DIR)/.pytest_cache" \
		"$(ROOT_DIR)/.ruff_cache" \
		"$(ROOT_DIR)/.mypy_cache" \
		"$(ROOT_DIR)/htmlcov" \
		"$(ROOT_DIR)/.coverage"
	@find "$(ROOT_DIR)/flask" "$(ROOT_DIR)/scripts" "$(ROOT_DIR)/tests" \
		"$(ROOT_DIR)/chordflask_base" "$(ROOT_DIR)/chordflask_maintain" \
		"$(ROOT_DIR)/chordflask_btc" "$(ROOT_DIR)/chordflask_demucs" \
		-type d -name __pycache__ -prune -exec rm -rf {} +
	@find "$(ROOT_DIR)/flask" "$(ROOT_DIR)/scripts" "$(ROOT_DIR)/tests" \
		"$(ROOT_DIR)/chordflask_base" "$(ROOT_DIR)/chordflask_maintain" \
		"$(ROOT_DIR)/chordflask_btc" "$(ROOT_DIR)/chordflask_demucs" \
		-type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

clean-report:
	@bash "$(ROOT_DIR)/scripts/clean_report.sh"
