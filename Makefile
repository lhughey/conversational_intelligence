VENV := .venv
# Describe a recorded run: make bench-gate NOTE="why this run" (see bench-results/HISTORY.md)
NOTE ?=
PY   := $(VENV)/bin/python

.PHONY: setup test test-cov test-e2e test-live testbed testbed-live bench bench-gate bench-gate-e2e bench-assessors bench-heldout label-heldout label-heldout-export label-heldout-import dataset contracts clean

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

testbed:                   ## run everything offline and record the result
	$(PY) scripts/testbed.py --note "$(NOTE)"

testbed-live:              ## same, including model-calling suites and assessors
	$(PY) scripts/testbed.py --live --note "$(NOTE)"

bench-assessors:           ## compare assessors across models (live, cached)
	$(PY) scripts/compare_assessors.py --note "$(NOTE)"

bench-gate:                ## evaluate the gate on the balanced split
	$(PY) -m convint.api.cli bench --gate --split synth --note "$(NOTE)"

bench-gate-e2e:            ## gate on synth: oracle inputs vs fed by the deterministic assessor (offline)
	$(PY) -m convint.api.cli bench --gate --split synth --e2e --assessor deterministic --note "$(NOTE)"

bench-gate-corpus:         ## same, on the realistic (skewed, weakly labelled) split
	$(PY) -m convint.api.cli bench --gate --split corpus --note "$(NOTE)"

bench-gate-human:          ## score against YOUR labels - the only validity evidence
	$(PY) -m convint.api.cli bench --gate --split human --note "$(NOTE)"

bench-heldout:             ## assessors vs YOUR held-out labels (live, cached; refuses below 20 labelled)
	$(PY) -m convint.api.cli bench --assessors --split heldout --assessor all --note "$(NOTE)"

label:                     ## interactive: judge the most informative unlabelled items
	$(PY) -m convint.api.cli label --split corpus --limit 15

label-conflicts:           ## only the items where rule and code disagree
	$(PY) -m convint.api.cli label --split corpus --disagreements-only --limit 20

label-all:                 ## interactive: judge every unlabelled item
	$(PY) -m convint.api.cli label --split corpus --limit 20

label-export:              ## alternative: write an editable file instead
	$(PY) -m convint.api.cli label --split corpus --export

label-import:              ## read decisions back out of that file
	$(PY) -m convint.api.cli label --split corpus --import

label-heldout:             ## interactive: label the held-out set (S/O per answer; resumable; never tuned on)
	$(PY) -m convint.api.cli label --split heldout --limit 0

label-heldout-export:      ## alternative: write data/heldout/label-sheet.md to fill in
	$(PY) -m convint.api.cli label --split heldout --export

label-heldout-import:      ## read held-out labels back out of that sheet
	$(PY) -m convint.api.cli label --split heldout --import

doctor:                    ## check credentials resolve from this repo's .env
	$(PY) -m convint.api.cli doctor

bench:                     ## assessor agreement + corpus replay (offline)
	$(PY) -m convint.api.cli bench

contracts:                 ## regenerate contracts/v1/*.json from the models
	$(PY) scripts/export_contracts.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info

dataset:                   ## rebuild the turn-decision dataset
	$(PY) -m convint.api.cli dataset build
