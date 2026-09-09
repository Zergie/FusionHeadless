.DEFAULT_GOAL := help

# Override with, for example, make check PYTHON=python3.
PYTHON ?= python
ifeq ($(OS),Windows_NT)
VENV_PYTHON := .venv/Scripts/python.exe
CLI_PYTHON := cli/.venv/Scripts/python.exe
else
VENV_PYTHON := .venv/bin/python
CLI_PYTHON := cli/.venv/bin/python
endif

.PHONY: help setup setup-cli setup-full setup-dev test compile check diff-check

help:
	@echo "setup       Create the server environment and install dependencies"
	@echo "setup-cli   Create the CLI environment and install dependencies"
	@echo "setup-full  Set up both the server and CLI environments"
	@echo "setup-dev   Install test dependencies into .scratch/deps"
	@echo "test        Run the full unittest suite without Fusion"
	@echo "compile     Check Python source compilation"
	@echo "check       Run tests, compilation, and git diff --check"

setup:
	$(PYTHON) -m venv .venv
	"$(VENV_PYTHON)" -m pip install -r requirements.txt

setup-cli:
	$(PYTHON) -m venv cli/.venv
	"$(CLI_PYTHON)" -m pip install -r cli/requirements.txt

setup-full: setup setup-cli

setup-dev:
	$(PYTHON) -m pip install --upgrade --target .scratch/deps -r requirements.txt -r cli/requirements.txt

test:
	$(PYTHON) -c "import os,pathlib,sys,unittest; d=str(pathlib.Path('.scratch/deps').resolve()); os.environ['PYTHONPATH']=d+os.pathsep+os.environ.get('PYTHONPATH',''); sys.path.insert(0,d); r=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(0 if r.wasSuccessful() else 1)"

compile:
	$(PYTHON) -m compileall -q $(wildcard *.py) routes mcp startup cli tests

diff-check:
	git diff --check

check: test compile diff-check
