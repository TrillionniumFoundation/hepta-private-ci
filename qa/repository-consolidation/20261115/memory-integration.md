# Memory branch integration checkpoint

## Status and identities

This ordinary merge combines `f41db48d00ebcfc1b6217313197d2c4b99bc666a`
with `1657238edcc0793bc353c931f9ca445ef992315c`. All 138 Git conflicts
were reviewed and resolved. `memory/SOURCE_CHECKPOINT.json` fixes the changed
active source bytes. The first checkpoint is for continuing review and native
compilation; it is **not ready for main promotion**.

The following gates remain open at this checkpoint:

- The complete 1,624-boundary caller-proof diagnostic is running. Two new
  support modules already gated by their parents' `cfg(test)` now also carry
  file-level `#![cfg(test)]`; no ignored-path rule or scanner was weakened.
  New privileged Memory call sites still need explicit closed-set inventory.
- Rust formatting, compilation, owning-crate tests, and the new regressions
  have not run in this local environment because Rust tools are absent.
  Native validation must use these exact source bytes and the unified lock.
- The actual blob gate found 75 additional historical archive/receipt files
  above 512,000 bytes (351,656,533 bytes total). Their path/size inventory is
  recorded. They will be retained by exact Git object identity in this merge's
  incoming ancestry, with an offline checked restore tool. No new broad size
  exception is authorized by this checkpoint.
- The broader Python fixture suites need their explicit dependencies before
  missing-module outcomes can be counted as a completed test run. No model
  acquisition, training, campaign, or workflow dispatch was performed.

## Semantic conflict resolutions

Current Learning, Q24, HCSN, Notes, Desktop, completed-history, source-bound KG,
production startup, and Root-bound socket composition are retained. Memory
registration and read controls are added as independent optional interfaces.
The compatibility bootstrap requires paired explicit flags and refuses an
already-installed protected writer owner; it is not a protected startup bypass.

The recovered source anchor is captured in the shared recovered-writer helper
before acquiring or resuming the writer lease, while retaining live verifier
binding and the existing exact-cut behavior. CognitiveStore keeps its shared
commit gate, checkpoint barrier, observation pool close, main pool close, and
final lifetime fence. New Unix database creation uses private permissions and
no-follow flags before SQLite can create its journal files.

Neuron's calibrated and shadow profiles share the tick transaction. The
registered subject/objective, successor sequence, monotonic clock, body identity,
and remaining journal capacity are checked before invoking the model. The
existing calibrated regressions are retained; three additional shadow tests
assert zero extra model calls or journal/witness changes for rejected work.
Witness-only retry retains the original single model invocation. The existing
bootstrap-anchored recovery constructor is adapted to the composed profile
representation rather than lost during the refactor.

The incoming ZIP permission fix masks the archived mode to `0o777`, preserving
existing traversal/symlink protections and the stored/deflated fixture coverage.
The current YAML duplicate-key validation remains in place.

The dependency graph preserves the unified current Matrix 0.19.1, Keyring 4.2,
SQLite, ZIP, and Zstd choices. The older branch's Matrix/Keyring/dependency
rollback was not selected. The new process fix explicitly enables `process`
on the existing Tokio dependency; the unified native/Bazel graph must include
that feature. No external dependency package or version was invented.

All 95 Matrix 0.18 vendor add/add conflicts are exact documented before/after
formatting pairs: stage 2 matches the retained formatter output, stage 3 the
recorded input, including Git OID, byte size, and SHA-256. The current output is
preserved. The four i18n conflicts keep the maintained minimal patch, public
error name, and parser tests; the incoming alternate README is retained under
`memory/vendor/` as an archived proposal. This is an identity/semantic review,
not a new vendor build or runtime qualification.

## Process boundaries and Python checks

The incoming Rust worker killed only its direct child, then joined blocking
pipe threads without a deadline. A descendant retaining a pipe could outlive
the promised bound. The revised implementation uses one deadline for async
stdin, bounded stdout/stderr drains, and child exit; dropping those operations
closes the handles. It attempts Unix process-group cleanup on timeout,
cancellation, and successful direct-child exit, rejects a cleanup error, and
bounds reaping separately. Cleanup of the owned group is not an OS sandbox or
a claim to contain a process that deliberately escapes the group. Raw request
and receipt files are created privately with exclusive/no-follow opens on Unix.

The child environment is cleared and rebuilt from a runtime allowlist, with
offline model settings enforced. Seven focused Rust process tests cover blocked
stdin, cancellation, synthetic secret and Python-path exclusion, timeout with
a grandchild holding pipes, direct exit with inherited pipes, background child
cleanup after ordinary completion, and an output flood. They are pending native
execution; no PASS is inferred from their presence.

The separately reviewed Python process helper uses private regular files for
all three standard streams, an explicit environment allowlist, and owned POSIX
group cleanup. This closes both the stdout EOF wait and the large-stdin replay
wait discovered during review. The final six focused standard-library tests
passed locally against the exact hashes in `model-process-v2-local-tests.json`,
including a deliberately escaped stdin-holder fixture with explicit cleanup.
The original parent mismatch and raw-output tests remain. A separate set of
184 existing offline fixture tests across 32 modules passed with zero failures,
errors, or skips; `python-stdlib-tests.json` records its dependency versions and
scope. These tests do not execute a model or establish model quality.

Pure Cell evidence and Group adapters retain deny-all/advisory semantics.
Documentation now states that matching structural digests do not independently
authenticate a producer or prove physical model execution; their public value
types are not authority capabilities.

## Workflow and evidence controls

All 13 newly introduced research/diagnostic workflows use only manual dispatch
with a required boolean whose default is false, and every job checks the input.
The existing five workflows retain the unified baseline's behavior. Native
process checkout follows the explicitly selected `github.sha`. The lockfile
workflow generates/checks/uploads reviewable artifacts with read permissions;
its old authentication, commit, and push steps are removed. The four-checkpoint
Stem job additionally requires a separate operator-accepted-terms input,
default false, passed as an actual boolean instead of a hard-coded acceptance.

Five existing large research fixture exceptions are restricted to exact
independently verified SHA-256 identities, preserving current entries and the
size limit for replacements. Archive bytes and historical success/failure
records are retained as evidence only; they are not fresh qualification.

`memory/resolution-ledger.json` records per-path conflict choices. The new HIA
branches and all remote refs are outside this local checkpoint operation.

## Historical storage follow-up

The 75 oversized historical files are now indexed in
`memory/HISTORICAL_ASSETS.json` and retained in the ordinary merge's ancestor
objects. All 351,656,533 bytes were actually restored outside the repository
and verified against their original Git OIDs and SHA-256 values before removing
the current-tree copies. Nine offline storage regressions passed. The original
checkpoint's blob failure is preserved as the initial finding; the storage
follow-up reruns the real blob gate without adding exceptions.

## Process and fixture follow-up

The Rust async stdin future now owns and closes its descriptor immediately
after writing, so an ordinary worker reading to EOF can complete. An eighth
focused test uses the actual pinned production launcher as an explicitly
Bazel-declared resource and requires successful complete input/output, in
addition to the seven failure/lifetime tests. Rust execution remains pending.

Historical fixture restoration now refuses authenticated HTTP redirects,
checks a 2 MiB response budget with an extra-byte sentinel, validates canonical
base64 content, and binds the decoded bytes to the response's exact size and
Git blob ID. Original stronger task SHA-256 pins remain in their callers.
Five synthetic-transport tests passed both in the independent review and this
integrated worktree; no actual token or network request was used.

The final Python review records **383 unique passing tests across 57 modules**,
combining 184 original local tests, 194 ROG tests, and five fixture-restoration
regressions. Repeated runs are not counted twice. Earlier missing dependencies
and incomplete staging attempts remain in the evidence, followed by completed
runs with the required packages. The JSON summary and 105-record compressed
review bundle (plus its manifest) are `memory/memory-python-review-final.json`
and `memory/memory-python-offline-review.tar.gz`. Every bundled member's length
and SHA-256 was checked independently before committing it. No training,
acquisition, historical campaign, or downloaded model code was executed.

## Caller and platform follow-up

The reviewed Memory caller inventory now preserves all 1,624 original
boundaries and 809 original protected files while adding 20 explicit
boundaries, nine guard rows, and five reviewed caller extensions. All 25
changed or new boundaries and all nine guard rows passed a focused scan of
7,476 Rust files. `memory/callers-reviewed-additions.md` explains each
extension and its limits. The subsequent canonical full scan on fixed commit
`8ce85627f92ecd9ff6cc21afc75472302eb0bb9d` passed all 1,644 boundaries and
818 protected files in 895.953 seconds, with unchanged source inputs and empty
stderr. Complete raw output and source hashes are retained as lossless gzip
files with their command receipt. The real blob-size gate passed on that same
commit without broadening the asset exceptions.

The Rust process boundary now rejects non-Unix platforms before any file or
process side effect, because the public library route was not protected by
the Linux-only CLI bootstrap. Its new non-Unix refusal test is separate from
the eight Unix process tests and remains pending an actual supported runner.
Unix cleanup owns only descendants in the spawned process group; Linux's
launcher verifies its additional parent-death binding. No Windows or macOS
parent-death qualification follows from a Linux run.
