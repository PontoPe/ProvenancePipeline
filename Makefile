SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# Run from Git Bash or WSL on the Windows workstation — this is a POSIX Makefile.

OWNER    ?= pontope
REPO     ?= provenancepipeline
IMAGE    ?= ghcr.io/$(OWNER)/$(REPO)
TAG      ?= dev
REF      := $(IMAGE):$(TAG)

# The identity `cosign verify` must find in the Fulcio certificate. It is the
# whole trust anchor: keyless signing has no key, so this string plus the issuer
# is what separates "signed by our pipeline" from "signed by anybody".
IDENTITY ?= https://github.com/PontoPe/ProvenancePipeline/.github/workflows/release.yml@refs/heads/main
ISSUER   ?= https://token.actions.githubusercontent.com

VERSION  ?= dev
REVISION ?= $(shell git rev-parse HEAD)

# -race needs cgo, and the Windows workstation has no C toolchain: `go test
# -race` there fails with "-race requires cgo". CI runs on Linux and does use it.
ifeq ($(OS),Windows_NT)
RACE :=
else
RACE := -race
endif

# Verification always targets a digest, never a tag — a tag is a mutable pointer
# and the signature covers the digest. Resolve it from the registry if not given.
DIGEST ?=
digest = $(if $(DIGEST),$(DIGEST),$(shell docker buildx imagetools inspect $(REF) --format '{{.Manifest.Digest}}'))

.PHONY: help test build sbom scan run push sign attest verify verify-github evidence clean \
        policy-install policy-test demo demo-record

help: ## show targets
	@grep -hE '^[a-z][a-z-]*:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s $$'\t'

test: ## go vet + unit tests
	cd app && go vet ./... && go test $(RACE) ./...

build: ## build the demo image locally
	docker build \
		-f build/Dockerfile \
		--build-arg VERSION=$(VERSION) \
		--build-arg REVISION=$(REVISION) \
		--build-arg SOURCE_DATE_EPOCH=$$(git log -1 --pretty=%ct) \
		-t $(REF) .

sbom: ## generate SBOM (SPDX + CycloneDX) from the local image
	syft $(REF) -o spdx-json=sbom.spdx.json -o cyclonedx-json=sbom.cdx.json

scan: sbom ## fail on CRITICAL findings — same threshold as CI
	grype sbom:sbom.spdx.json --fail-on critical

run: ## run the image locally on :8080
	docker run --rm -p 8080:8080 --read-only --cap-drop=ALL $(REF)

push: ## push the local image
	docker push $(REF)

sign: ## keyless sign the published digest (normally CI's job)
	cosign sign --yes $(IMAGE)@$(call digest)

attest: ## attach the SBOM attestation (normally CI's job)
	cosign attest --yes --type spdxjson --predicate sbom.spdx.json $(IMAGE)@$(call digest)

verify: ## verify signature + SBOM + SLSA provenance as the cluster policy will
	@echo "==> ref $(IMAGE)@$(call digest)"
	cosign verify \
		--certificate-identity "$(IDENTITY)" \
		--certificate-oidc-issuer "$(ISSUER)" \
		$(IMAGE)@$(call digest)
	cosign verify-attestation --type spdxjson \
		--certificate-identity "$(IDENTITY)" \
		--certificate-oidc-issuer "$(ISSUER)" \
		$(IMAGE)@$(call digest) \
		| jq -r '.payload | @base64d | fromjson | .predicateType'
	cosign verify-attestation --type slsaprovenance1 \
		--certificate-identity "$(IDENTITY)" \
		--certificate-oidc-issuer "$(ISSUER)" \
		$(IMAGE)@$(call digest) \
		| jq -r '.payload | @base64d | fromjson | .predicate'

verify-github: ## verify GitHub's own build provenance (gh, not cosign — see ADR-005)
	gh attestation verify oci://$(IMAGE)@$(call digest) \
		--repo PontoPe/ProvenancePipeline \
		--signer-workflow PontoPe/ProvenancePipeline/.github/workflows/release.yml

evidence: ## regenerate docs/evidence from a live verification run
	./scripts/collect-evidence.sh

clean:
	rm -f sbom.*.json provenance.json

# --- admission control ---

# --server-side is required, not cosmetic: Kyverno's CRDs exceed the 262144-byte
# limit on the last-applied-configuration annotation that a client-side apply
# writes.
policy-install: ## install Kyverno + the verifyImages policy
	./cluster/bootstrap/fetch-upstream.sh
	kubectl apply -k cluster/bootstrap --server-side
	kubectl -n kyverno rollout status deploy/kyverno-admission-controller --timeout=300s
	kubectl apply -f policies/kyverno/

# --registry is required. Without it the CLI cannot fetch signatures from the
# registry and every case degrades into an error, so a suite that passes without
# it has verified nothing.
policy-test: ## kyverno policy tests — allow and deny paths
	kyverno test tests/ --registry

demo: ## the money shot — signed pod admitted, unsigned pod denied
	./scripts/demo.sh

# Records, audits the cast for leaked secrets, renders, and refuses to promote
# anything that matches. Recipe and reasoning: docs/demo-recording.md
demo-record: ## re-record docs/img/demo.gif from scripts/demo.sh
	DEMO_SCRIPT=./scripts/demo.sh \
	TITLE="ProvenancePipeline: a cluster refusing an unsigned image" \
	OUT_DIR=docs/img NAME=demo \
	./scripts/demo-record.sh
