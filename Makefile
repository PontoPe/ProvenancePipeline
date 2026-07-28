SHELL := /bin/bash
IMAGE ?= ghcr.io/OWNER/provenance-demo
TAG   ?= dev
REF   := $(IMAGE):$(TAG)
IDENTITY ?= https://github.com/OWNER/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main
ISSUER   ?= https://token.actions.githubusercontent.com

.PHONY: help build sbom scan push sign attest verify policy-install policy-test demo clean

help: ## show targets
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s $$'\t'

build: ## build the demo image
	docker build -t $(REF) build/

sbom: ## generate SBOM (SPDX + CycloneDX)
	syft $(REF) -o spdx-json=sbom.spdx.json -o cyclonedx-json=sbom.cdx.json

scan: sbom ## fail on CRITICAL findings
	grype sbom:sbom.spdx.json --fail-on critical

push: ## push image to registry
	docker push $(REF)

sign: ## keyless sign the pushed digest
	cosign sign --yes $$(cosign triangulate --type digest $(REF))

attest: ## attach SBOM + SLSA provenance attestations
	cosign attest --yes --type spdxjson --predicate sbom.spdx.json $(REF)

verify: ## verify signature + provenance as the cluster would
	cosign verify --certificate-identity=$(IDENTITY) --certificate-oidc-issuer=$(ISSUER) $(REF)
	cosign verify-attestation --type spdxjson --certificate-identity=$(IDENTITY) --certificate-oidc-issuer=$(ISSUER) $(REF)

policy-install: ## install Kyverno + the verifyImages policy
	kubectl apply -k cluster/bootstrap
	kubectl apply -f policies/kyverno/

policy-test: ## kyverno policy unit tests
	kyverno test tests/

demo: ## the money shot — signed pod admitted, unsigned pod denied
	./scripts/demo.sh

clean:
	rm -f sbom.*.json
