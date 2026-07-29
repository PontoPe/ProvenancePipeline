# syntax=docker/dockerfile:1.19
#
# Build context is the repository root (see .dockerignore).
#
# Base images are pinned by digest, not by tag. A tag is a mutable pointer; the
# same argument that makes the admission policy refuse tags applies to what this
# pipeline consumes. See ADR-002 in docs/architecture.md.

# golang:1.26-alpine
ARG GO_IMAGE=golang@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2
# gcr.io/distroless/static-debian12:nonroot
ARG RUNTIME_IMAGE=gcr.io/distroless/static-debian12@sha256:f5b485ea962d9bd1186b2f6b3a061191539b905b82ec395de78cbfae51f20e35

FROM --platform=$BUILDPLATFORM ${GO_IMAGE} AS build

WORKDIR /src

# go.sum is absent on purpose: the service has no third-party modules.
COPY app/go.mod ./
RUN go mod download && go mod verify

COPY app/ ./

ARG TARGETOS
ARG TARGETARCH
ARG VERSION=dev
ARG REVISION=unknown
# Set by the build workflow to the commit timestamp so the layer metadata does
# not carry the wall-clock time of the build.
ARG SOURCE_DATE_EPOCH

RUN CGO_ENABLED=0 go test ./...

# -trimpath strips absolute build paths, -buildid= drops the non-deterministic
# build ID: together they make the binary byte-identical across builds of the
# same source. Reproducibility is what makes the provenance falsifiable.
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build \
      -trimpath \
      -ldflags="-s -w -buildid= -X main.version=${VERSION} -X main.revision=${REVISION}" \
      -o /out/provenance-demo .

FROM ${RUNTIME_IMAGE}

# distroless :nonroot already runs as uid 65532 and ships no shell and no package
# manager. Restated explicitly so the guarantee survives a base image swap.
USER 65532:65532

COPY --from=build /out/provenance-demo /provenance-demo

EXPOSE 8080
ENTRYPOINT ["/provenance-demo"]

LABEL org.opencontainers.image.source="https://github.com/PontoPe/ProvenancePipeline" \
      org.opencontainers.image.description="Minimal service used to demonstrate signed, attested container provenance." \
      org.opencontainers.image.licenses="MIT"
