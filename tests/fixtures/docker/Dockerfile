# Smallest Dockerfile that hadolint accepts at its strictest useful settings:
# a digest-pinned base, no `latest`, a pinned package version, and an explicit
# non-root user. It builds in seconds and pulls one small layer.
FROM alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce

# hadolint wants versioned packages; `--no-cache` keeps the layer small.
RUN apk add --no-cache tini=0.19.0-r3

RUN addgroup -S fixture && adduser -S fixture -G fixture
USER fixture

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["echo", "ci-workflows container fixture"]
