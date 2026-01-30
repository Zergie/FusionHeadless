PYTHON := python3.14

.PHONY: setup clean check-python
setup: .venv/lib64/python3.14/site-packages/pygments/__init__.py

check-python:
	@$(PYTHON) --version 2>&1 | grep "Python 3.14" > /dev/null || \
		(echo "Error: Python 3.14 is required, installed is $$( $(PYTHON) --version ) ." && exit 1)

.venv/bin/activate: check-python
	$(PYTHON) -m venv .venv

.venv/lib64/python3.14/site-packages/pygments/__init__.py: requirements.txt | .venv/bin/activate
	.venv/bin/pip install -r requirements.txt && touch $@

clean:
	rm -rf .venv