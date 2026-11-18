PYTHON ?= $(shell python3 -c "import sys" >/dev/null 2>&1 && echo python3 || echo python)

.PHONY: test findings

test:
	$(PYTHON) -m unittest discover -s tests -v

findings:
	$(PYTHON) plearun_cli.py reports/report_fictional_02.txt records > findings.json
