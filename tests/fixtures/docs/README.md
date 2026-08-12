# Documentation fixture

This tree exists so `docs-quality.yml` has something real to check. It is
deliberately small and deliberately correct: the workflow runs a spell checker,
a Markdown linter and a link checker, so any sloppiness here would show up as a
failure of the workflow rather than of the fixture.

## Why there are no external links

The link checker resolves every link it finds. An external link would make this
fixture fail whenever that site is slow or moved, which would turn a contract
proof into a network test. The only link below is relative, and the file it
points at is committed alongside this one.

See [the second page](second-page.md) for the rest of the fixture.
