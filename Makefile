VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: setup test test-cov test-e2e test-live bench bench-gate bench-assessors dataset contracts clean

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -e ".[dev]"

test:                      ## tier 1+2: pure domain + contract. no network, no key.
	$(PY) -m pytest

test-cov:
	$(PY) -m pytest --cov=convint --cov-report=term-missing

test-e2e:                  ## cross-language proof: Node client vs live HTTP server
	$(PY) -m pytest -m e2e -v

test-live:                 ## opt in to tests that call a real model API
	$(PY) -m pytest -m live

bench-assessors:           ## compare assessors across models (live, cached)
	$(PY) scripts/compare_assessors.py

bench-gate:                ## evaluate the gate against turn-decision labels
	$(PY) -m convint.api.cli bench --gate

bench:                     ## assessor agreement + corpus replay (offline)
	$(PY) -m convint.api.cli bench

contracts:                 ## regenerate contracts/v1/*.json from the models
	$(PY) scripts/export_contracts.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info

dataset:                   ## rebuild the turn-decision dataset
	$(PY) -m convint.api.cli dataset build
