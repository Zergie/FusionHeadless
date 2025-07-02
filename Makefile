PYTHON := python3

.PHONY: setup clean
setup: .venv/lib64/python3.12/site-packages/pygments/__init__.py

.venv/bin/activate:
	$(PYTHON) -m venv .venv

.venv/lib64/python3.12/site-packages/pygments/__init__.py: requirements.txt | .venv/bin/activate
	.venv/bin/pip install -r requirements.txt

clean:
	rm -rf .venv