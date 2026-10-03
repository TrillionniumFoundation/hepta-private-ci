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
32 MiB of selected payload and its header (plus one metadata overflow-probe byte). This intentionally adds linear read
cost; there is no constant-time or production-latency claim. A one-MiB fixture
reports eight repeated read costs without asserting a machine-specific deadline
and verifies that both files are byte-identical afterward. The local unoptimized fixture
read a 188,198-byte manifest plus one MiB of payload eight times in 278,447
microseconds total; this is an informational local cost, not target-host acceptance.

## Verification

- The two original regressions fail before the repair; this is actual native
  execution, not a source-only inference.
- Eight new tests cover selected corruption, missing/truncated/header faults,
  five first-read ports, valid metadata rollback, mutation/no-op rejection,
  sticky poison, explicit reopen, unselected tails, unchanged file bytes and a
  still-unclaimed final-use grant successfully admitted after explicit reopen.
- Complete local registry and optimizer suites: 154 passed (97 registry and
  57 optimizer), zero skipped. Scoped formatting and strict all-target Clippy pass.
- Dedicated exact-source Linux/macOS hosted tests, formatting and strict lint
  are defined; only completed receipts for the final published head count.

Ordinary authenticated product ingress, independently retained recovery witness
custody, actual provider-send currentness, tokenizer/P0 review, retention and
scale, installed-host acceptance and independent outcomes remain open. No
production, activation, promotion or release qualification is advanced.
