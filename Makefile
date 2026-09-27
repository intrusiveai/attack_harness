OPERATOR_ROOT ?= ../operator_sandbox
PYTHON ?= $(OPERATOR_ROOT)/.venv/bin/python

.PHONY: test
test:
	PYTHONPATH="$(CURDIR)/src:$(OPERATOR_ROOT)/contracts/python" OPERATOR_CONTRACT_SOURCE="$(abspath $(OPERATOR_ROOT))/schemas" $(PYTHON) -m unittest discover -s tests -v
