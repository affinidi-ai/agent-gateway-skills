# Checks for the affinidi-agent-gateway skill. `make help` lists the targets.
#
# CI's check job runs `make ci`; its plugin-validate job runs the standard validators. `make check` also needs the fabric binary; `make e2e` needs a live gateway.
# Missing inputs are errors, never skips.

PYTHON ?= python3
FABRIC ?=

.PHONY: help validate unit ci cli-reference cli-check e2e check all

help: ## List the targets
	@awk 'BEGIN { FS = ":.*## " } /^[a-z-]+:.*## / { printf "  %-14s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

validate: ## Offline checks the standard validators lack: size, links, drift matrix, banned content, shipped content, fabric commands, generated files
	$(PYTHON) scripts/validate.py

unit: ## Unit tests for every script and the e2e runner
	$(PYTHON) -m unittest discover -v -s tests/unit -p 'test_*.py'

ci: validate unit ## What CI's check job runs (offline)

cli-reference: ## Regenerate .github/fabric-cli-snapshot.json and references/commands.md from the fabric binary
	$(PYTHON) scripts/gen-cli-reference.py $(if $(FABRIC),--fabric "$(FABRIC)")

cli-check: ## Fail if the generated command reference differs from the fabric binary (FABRIC=...)
	@if [ -z "$(FABRIC)" ]; then \
		echo "cli-check: set FABRIC to a fabric binary built from the baseline commit in .github/skill-drift-matrix.json" >&2; \
		exit 2; \
	fi
	$(PYTHON) scripts/gen-cli-reference.py --check --fabric "$(FABRIC)"

e2e: ## Literate end-to-end cases against a live gateway (FABRIC_E2E_HOST, FABRIC_E2E_TOKEN; FABRIC or fabric on PATH)
	PYTHON="$(PYTHON)" $(if $(FABRIC),FABRIC="$(FABRIC)") tests/e2e/run.sh

check: ci cli-check ## Full verification: ci plus the CLI reference against the fabric binary

all: check e2e ## Everything, including the live end-to-end cases
