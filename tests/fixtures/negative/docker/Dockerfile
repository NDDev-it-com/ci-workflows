# Breaks hadolint at the default `warning` threshold: DL3007 (latest tag) and
# DL3018 (unpinned apk package). Both are exactly what the positive fixture
# avoids, so the pair brackets the rule.
FROM alpine:latest

RUN apk add --no-cache curl

CMD ["echo", "this fixture must fail hadolint"]
