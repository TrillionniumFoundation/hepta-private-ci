# Canonical paths for owned Mac test fixtures

This candidate follows the complete failed-test artifacts for source
`97ab00451799667faebac2c455a1e3176ebc90cb`. It changes test setup only. The
production canonical-path, stable-handle, symlink, permission, and identity
checks remain unchanged.

## Cognitive-store reopen fixtures

Both Mac jobs reported the same four test names with the explicit error that
the per-agent cognitive root must be canonical and must not traverse a
symlink. The common initial setup already canonicalized its created fleet
root, but three reopen paths rebuilt that root from the original TempDir
spelling. One separate-store negative control also omitted canonicalization.

The four sites now canonicalize the already-created, owned Unix fleet root,
matching their initial setup. Windows construction is unchanged. TempDir
ownership and all lease, store-binding, replay, tombstone, and count assertions
remain intact.

## Local executor-skill fixtures

Two restricted executor-skill cases failed in each Mac job on all three
existing attempts. The retained logs show an authorized reference-read error
followed by JSON parsing of its model-facing error text. They also show a
local environment root spelled under `/var/folders`.

The Darwin authorized-read implementation obtains the final path with
`F_GETPATH` and checks it against the materialized policy roots. That access
check uses lexical prefix matching. A `/private/var` final path does not match
a `/var` policy prefix. The existing authorized-read unit fixtures already
create their TempDir under the canonical temporary parent for this reason.

The shared host-local `TestEnv` now follows that same construction on macOS.
It retains the same owned TempDir, environment ID, execution-environment
selection, and permissions. The Docker/Wine target-native constructor and
all other operating systems retain their original construction. No arbitrary
user path or production policy is canonicalized by this change.

The source establishes a sufficient path-spelling mismatch. The old skill
error redacts the exact failing internal stage, so it does not prove that no
other stable-handle or authorization failure existed in that attempt.

## Qualification boundary

This is a source candidate, with no new Rust build or native test result at
preparation time. The next source must run the four original cognitive tests,
the complete executor-skills suite (including its denied-reference and
approval controls), and the existing host-local environment tests. All
original deadlines, retry settings, assertions, and production permission
gates are retained. Repeated attempts are not distinct test scenarios.
