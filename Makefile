OPERATOR_ROOT ?= ../operator_sandbox
PYTHON ?= $(OPERATOR_ROOT)/.venv/bin/python
PLATFORM ?= linux/arm64
PLATFORM_SLUG := $(subst /,-,$(PLATFORM))
CONTRACT_PACKAGE := build/context/contracts
CONTRACT_COMMIT := e6f3ccd1a08ea3e1defdbb1a5514ff55dbfa6220

.PHONY: test verify-source verify-contracts contract-package image inspect-image inspect-stopped-image
test:
	PYTHONPATH="$(CURDIR)/src:$(OPERATOR_ROOT)/contracts/python" OPERATOR_CONTRACT_SOURCE="$(abspath $(OPERATOR_ROOT))/schemas" $(PYTHON) -m unittest discover -s tests -v

verify-source:
	$(PYTHON) build/source_lock.py --root . --lock build/source-lock.json

contract-package: $(CONTRACT_PACKAGE)/package.json

$(CONTRACT_PACKAGE)/package.json:
	@test "$$(git -C "$(OPERATOR_ROOT)" rev-parse HEAD)" = "$(CONTRACT_COMMIT)"
	@mkdir -p build/context
	@cd "$(OPERATOR_ROOT)" && go run ./cmd/operatorctl contract build \
		--source "$$(pwd)" --output "$(abspath $(CONTRACT_PACKAGE))" \
		--package-version 0.0.0

verify-contracts: contract-package
	PYTHONPATH="$(CURDIR)/src:$(OPERATOR_ROOT)/contracts/python" $(PYTHON) \
		build/prepare_release.py --check-contract \
		--contract-package "$(CONTRACT_PACKAGE)" \
		--contract-lock build/contract-lock.json

image: verify-source verify-contracts
	@mkdir -p dist
	docker buildx build --platform "$(PLATFORM)" --target runtime \
		--build-arg SOURCE_DATE_EPOCH=0 --provenance=mode=max \
		--attest "type=sbom,generator=docker.io/docker/buildkit-syft-scanner:stable-1@sha256:ae4f3b554449e7e25548e7d8ccc029d17357348e30c6e3df01b92bc93654d6a9" \
		--output "type=oci,dest=dist/attack-harness-$(PLATFORM_SLUG).oci.tar,rewrite-timestamp=true" .
	$(MAKE) inspect-image PLATFORM="$(PLATFORM)"

inspect-image:
	$(PYTHON) build/inspect_oci.py \
		--archive "dist/attack-harness-$(PLATFORM_SLUG).oci.tar" \
		--platform "$(PLATFORM)" \
		--contract-lock build/contract-lock.json \
		--output "dist/attack-harness-$(PLATFORM_SLUG).build-report.json"

# Run after `make image`. The Docker archive has the attested OCI candidate's
# exact config and layers, but omits attestations so Docker exposes a resolvable
# single-manifest ID to Operator's immutable recheck.
inspect-stopped-image: verify-source verify-contracts
	@test -f "dist/attack-harness-$(PLATFORM_SLUG).build-report.json"
	docker buildx build --platform "$(PLATFORM)" --target runtime \
		--build-arg SOURCE_DATE_EPOCH=0 --provenance=false \
		--output "type=docker,dest=dist/attack-harness-$(PLATFORM_SLUG).inspection.tar,rewrite-timestamp=true" .
	$(PYTHON) build/inspect_stopped_image.py --source-root . \
		--operator-root "$(OPERATOR_ROOT)" --platform "$(PLATFORM)" \
		--archive "dist/attack-harness-$(PLATFORM_SLUG).inspection.tar" \
		--build-report "dist/attack-harness-$(PLATFORM_SLUG).build-report.json" \
		--output "dist/attack-harness-$(PLATFORM_SLUG).inspection-report.json"
