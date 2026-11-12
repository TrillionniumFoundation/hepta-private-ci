# Exact remaining publication precondition

The real export remains on desktop at
`/home/qian-qi/hcsn-real-replay-c06d-export-v1.zip`: 11,397,159 bytes,
SHA-256 `37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75`.
Read-only export job `1a1ce7e3837-2564-16c9` completed successfully with zero
model executions. It contains the six selected real C2 checkpoints, original
source and prepared episode bytes; no factorial checkpoint is substituted.

Desktop noninteractive-gh inspection key
`c06d-desktop-c2-github-auth-inspect-v1` received MCP timeouts on its initial
request and same-key reconciliation. No job ID or authorization result has
been recovered. Registry reconciliation also timed out without an operation ID.
This establishes **UNKNOWN authorization observation**, not absent credentials
or denied permission. No native publisher invocation or Git write is claimed.
Binary archive reads also timed out, so there is currently no complete local
archive or observed GitHub blob/ref that the CPU lane can use.

The included `publish_native_gh.py` is an unexecuted preparation copied exactly
from the root delivery. It contains no credential. It uses normal gh identity
and push-permission checks, validates the exact export bytes, then creates an
immutable blob, independent artifact branch and Draft PR from evidence parent
`a832b028abdf1a1c9ab66534332457c6d76a91ca`. Model source remains
`5cb83d9c76beedf4c1c917e4bf561f5f26261ce7`. It does not modify the source PR ref.

First reconcile the existing inspection identity using its original request.
Only after an observed normal noninteractive authorization result should the
prepared publisher be launched once with a new, retained operation key. Its
state directory is `/home/qian-qi/hcsn-c2-native-gh-export-c06d-v1`.
The publisher deliberately creates this directory once; it is not an automatic
resume engine. After an uncertain write, inspect retained stage records and
the exact Git blob/commit/ref before another action. Do not remove the directory,
force a ref, or restart main under a new key to hide an uncertain outcome.

The manifest uses `hcsn-real-replay-export-parts-v1`, fixed archive size/hash and
ordered relative part filename `part-000.zip`. After immutable artifact commit
and byte identities are independently observed, update `CPU-ARTIFACT.json` to
FROZEN with that exact commit. The ubuntu-latest lane then checks out source and
artifact separately, verifies the archive, derives the explicit CPU profile,
and starts fresh bounded recovery workers. Missing publication currently fails
before model setup; a synthetic fixture is never used as a replacement.

Native training attempts `1a1ce727d17-2564-167b` and
`1a1ce768bc3-2564-1695` were authoritatively cancelled by SIGTERM, not the declared
timeout. Their optimizer-call totals remain UNKNOWN. New successful CPU recovery
would qualify only its own six checkpoint continuities and 26 verified calls.
Independent complete C2 training replays remain zero; HOLD_NO_GO remains.
