# Original Objective sender: execution record

The final candidate extends the original Hepta CognitiveStore and
ProductionDurableWriter. It retains the exact Objective request and complete
origin in the original database, occupies one durable sending opportunity,
requires an independent current-cut acknowledgement, and preserves unknown,
observation and local cancellation state without regranting send after restart.

Base: `16418ddc3416a38a122b883cee46e2d3583cbd41` / tree `43fde98e9ea789b81b941e48bb65300c76c4292c`.
Source-only candidate tree: `7f5f940a549afeb7803f952c656264eb5fba7680`. The publication manifest binds
all 19 changed paths to original Git preimages and final SHA-256 values.
All 9,111 original source blobs and file modes were checked before and after
the final run; the candidate overlay was explicit. No Cargo manifest,
Cargo.lock or Bazel dependency lock changed. Existing `BUILD.bazel` includes
the new migration through its original `migrations/**` compile-data glob.

## Executed verification

| Original gate | Actual result | Qualification |
| --- | --- | --- |
| `just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1 -p codex-hepta-memory --lib` | 317 executed / 317 passed / 0 failed; nextest separately reports 8 skipped | Final formatted candidate, Rust 1.95.0, 115.831 seconds of test execution; not an Agentd or native guest qualification. |
| Focused original sender/schema/recovery entry | 42 / 42 passed before final formatting; all included in final full run | 16 new sender tests, 14 original recovery tests, original schema and related regressions. |
| Original `just fmt` then `just fmt --check` | Both exit 0 | Final source byte identities are in the receipts. |
| Original scoped `just fix -p codex-hepta-memory --locked --profile dev-small --lib` | Incomplete; final attempt controlled exit 130 | Additional check metadata crossed the agreed 256 MiB shared-memory boundary, before the owning-package lint analysis. No source rewrite occurred. This is not a Clippy pass. |
| Original Agentd bridge tests | Three authored, zero executed | Installed same-owner capability, uninstalled refusal, and actual AuthBus body cross-package digest compatibility remain separate package gates. |

The final package run includes actual second-process uniqueness and three child
process exits immediately after committed request, observation and local-cancel
cuts. The children exit without Rust destructors. Original exact-cut recovery
then refuses to return another send permission. Test-only checkpoint probes do
not authenticate a production current-cut service.

The original recovery regressions cover current/predecessor witnesses, exact
current-cut writable activation, cold read-only recovery, pending WAL refusal,
physical FTS corruption, hostile file identities, bounded rows and unknown
tables, exclusive owner fencing, graceful close, and post-rename unknown state.
`execution-summary.json` contains every executed test name and the exact 14
original recovery names.

## Earlier failures were retained and resolved

- The first focused attempt stopped at the storage guard before the candidate
  compiled. A later attempt reached an actual test-only `SqlSafeStr` compile
  failure; the test now uses the original static trigger DDL.
- The first executing focused run had 39 passes and three failures. Fixes kept
  the production gates intact: a new lease epoch receives a distinct original
  fencing token; the tamper fixture uses separate static statements in the
  original transaction; the crash fixture enters original production recovery
  before its crash boundary. The wrapper initially rejected the generated
  nextest JUnit file. Its recovered receipt preserves that reporting failure
  without inventing a lost subprocess exit code.
- The first full run had 316 passes and one stale migration assertion: actual
  compiled migrations were 1 through 17 while the old test expected 1 through
  16. Only that expected original migration chain changed. The final full run
  above re-executed the complete library successfully.
- The first Clippy invocation was rejected because the restored source had no
  discoverable Git checkout. Validation then fetched and verified the exact
  original commit into external local Git metadata. The next original Clippy
  attempt ran but hit the resource boundary. Its 43,350,215 bytes of newly
  produced check-only metadata were SHA-recorded before removal; the original
  linked test graph, source, cache and locks remained intact.

## Legacy fresh initialization remains a separate boundary

An actual diagnostic of a legacy fresh `CognitiveStore::open` crash observed a
0600 main database but 0644 WAL/SHM sidecars under the inherited umask. Original
production recovery correctly rejects those identities. The patch does not
chmod an existing source, weaken recovery, or add a fallback to legacy open.
The positive crash tests explicitly establish test genesis, close it, enter
the original `open_with_recovery`, and only then exercise production commits
and process death. This is not a new production first-provisioning service.

## Remaining production work

1. A real independent checkpoint host must authenticate and fence publishers,
   durably ACK the exact full original cut, and handle cancellation without
   late publication. This slice requires that capability and supplies no
   production default or echo implementation.
2. Old-schema production anchors intentionally fail the new schema oracle.
   An authorized upgrade and a new independently authenticated current cut are
   still required; legacy open cannot repair a rejected production source.
3. The original Agentd package must execute the three bridge regressions, and
   Clippy must complete on a runner with adequate space. Memory passing does
   not substitute for either gate.
4. Trusted Session adapter composition and original journal ACK publication
   must remain bound to real owners. A CognitiveStore cut is not an Objective
   history anchor; a local cancel is not RunCancel; a retained unknown is not
   permission to resend. Other original writer domains still need their own
   checkpoint publication integration.

No native guest, QEMU, hardware, model turn or actual Objective dispatch ran as
part of this candidate's memory qualification. No remote write was performed
by the implementation agent. Source publication and merge remain the parent
reviewer's actions.
