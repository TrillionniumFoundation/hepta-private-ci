# Prompt live-owner integrity audit, 2026-10-03

## Reproduced defect and correction

The review starts from PR #1324 source `b7a00c70b1c68fb179f19640e9a2129c49cbb8fe`.
Two registered regressions fail against its unchanged production code:

- Changing a selected payload extent still allows a later owner commit to return
  success, even though the resulting store cannot recover that selected payload.
- Removing selected metadata still allows the open owner to return its cached
  authoritative registry.

The owner now retains the exact metadata digest selected at open or successful
publication. Authoritative entry points stream-verify that metadata and each
selected payload extent. Failure atomically poisons the owner before views,
mutation closures, unchanged retries or initial final-use grant claims proceed.
The first check returns its concrete error; later calls return `ReopenRequired`.
Restoring the fixture bytes cannot silently reactivate the same owner.

The check never repairs media. A valid unselected append remains unselected and
reads/no-op retries do not trim it. Existing publication orders, journal/grant
identities, storage schemas, digest domains, migration behavior and secure Unix
path policy are unchanged. `requires_reopen` is now a runtime method rather than
`const fn` because read-side poison uses an atomic flag; existing repository
callers use it at runtime. No new public mutation authority is introduced.

## Scope and cost

The existing exclusive owner lock remains the concurrency contract. Checks are
entry-point observations, not atomic isolation from a concurrent hostile writer,
an independent current-cut witness, physical-send revocation, Windows secure
storage support, or proof of off-host durability. Pure `PromptRegistry` values and
previously returned borrowed views do not become persistent owners.

Each check reads bounded metadata and selected payload bytes using fixed 32-KiB
hash scratch space. Worst-case input is the existing 32-MiB metadata ceiling plus
32 MiB of selected payload and its header (plus one metadata overflow-probe byte).
This intentionally adds linear read cost; there is no constant-time or
production-latency claim.

Independent review identified a consumer amplification in the first candidate:
for K selected items, compile and prepare each obtained K+2 durable views. At the
16-item cap, a real one-MiB consumer fixture read exactly 19,782,450 bytes per
compile, or 18 complete 1,099,025-byte selected images. An exact-byte assertion
failed twice before the correction. The original eight isolated registry-read
probe did not establish consumer cost and is superseded by this actual batch.

Both public operations now obtain a fresh durable view once, use that same
immutable borrow for exercise and private payload materialization, and discard it
when the operation returns. There is no global cache or cross-boundary reuse.
The corrected Linux fixture reads exactly 1,099,025 bytes for compile and again
for prepare. Its process-isolated `/proc/self/io` accounting subtracts the
counter-read bytes; no timing threshold, tracing permissions or production
instrumentation is used. Selected-byte corruption before a subsequent prepare
still rejects and poisons, including after the bytes are restored.

Local unoptimized batch times were 1,321,261 / 1,643,153 microseconds for compile /
prepare before correction and 799,002 / 1,086,528 afterward. Remaining in-memory
selection/digest costs are not removed; reduced disk reads do not imply an
18-fold latency improvement or target-host acceptance.

## Verification

- The two original regressions fail before the repair; this is actual native
  execution, not a source-only inference.
- Seven new owner tests cover selected corruption, missing/truncated/header faults,
  five first-read ports, valid metadata rollback, mutation/no-op rejection,
  sticky poison, explicit reopen, unselected tails, unchanged file bytes and a
  still-unclaimed final-use grant successfully admitted after explicit reopen.
- Final local registry, optimizer and Intelligence suites: 249 passed across
  five binaries (96 registry, 57 optimizer, 94 Intelligence library and two
  integration tests), zero skipped. Registry/optimizer strict Clippy passes.
  Combined Intelligence strict lint fails in unchanged canonical.rs (large
  outcome enum) and ndu_stochastic_admission_tests.rs (`expect` calls); no
  suppression or unrelated repair is included.
- A real 16-selection consumer test checks both public boundaries, exact Linux
  byte counts, unchanged selected files and corruption before the next prepare.
- Dedicated exact-source Linux/macOS hosted tests, formatting and strict
  registry/optimizer lint are rerun. Earlier green candidate `14365d18` receipts
  are not relabelled as the corrected candidate.

Ordinary authenticated product ingress, independently retained recovery witness
custody, actual provider-send currentness, tokenizer/P0 review, retention and
scale, installed-host acceptance and independent outcomes remain open. No
production, activation, promotion or release qualification is advanced.
