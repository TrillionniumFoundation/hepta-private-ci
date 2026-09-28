# channel.matrix qualification matrix

Status labels: `source` means implementation/fixture exists; `executed` requires a passing receipt for that exact execution scope; `external` requires the named real target host. Source presence, compilation or a workflow definition is never execution evidence. `QUALIFICATION_SCENARIOS.json` is the closed, ordered machine inventory for MATRIX-Q01–Q29; every entry that declares native tests must be reported as passed by the exact-candidate JUnit ledger in both lanes. For the latest canonical-content, sealed-permit and legacy-hold changes, read [FINAL_CONTENT_BOUNDARY_V2.md](FINAL_CONTENT_BOUNDARY_V2.md). None of the local Python/SQLite results below establish native or homeserver qualification.

## 1. Required scenarios

| ID | Scenario | Required oracle | Current gate |
|---|---|---|---|
| MATRIX-Q01 | normal send | SDK event ID is transport accepted; matching sync atomically confirms ledger/outbox | source; exact-head execution required |
| MATRIX-Q02 | ACK/response loss | accepted/indeterminate, same transaction after restart, later sync confirms | source |
| MATRIX-Q03 | HTTP 429 | typed Matrix Retry-After honored with bounded jitter; no hot loop | source; real homeserver receipt required |
| MATRIX-Q04 | server accepts then connection drops | never marked failed; terminal only after trusted observation | source fault seam |
| MATRIX-Q05 | revoke after claim, before entry | zero physical entry after rejection; fresh attempt/grant required | source |
| MATRIX-Q06 | crash after remote acceptance before local commit | same transaction and restart reconciliation | hermetic Synapse source fixture |
| MATRIX-Q07 | matrixd restart | transaction, claim history and verified authority lineage survive | source; exact-head native execution required |
| MATRIX-Q08 | supervisor restart/orphan | exact lease/adoption or fenced rejection | supervisor source tests and Synapse fixture |
| MATRIX-Q09 | redaction | confirmed event becomes redacted in the same sync-owner transaction | source |
| MATRIX-Q10 | sync gap/reconnect | no duplicate projection/send; cursor cannot skip terminal event | source |
| MATRIX-Q11 | room/device/session generation change | old scope/grant/daemon fenced before I/O | source; authenticated session-domain qualification required |
| MATRIX-Q12 | encrypted room rotation | session/device restoration and terminal reconciliation | external encrypted homeserver |
| MATRIX-Q13 | authenticated backup restore | revoked/redacted content and old sessions do not resurrect | external protected restore profile |
| MATRIX-Q14 | later rejection after acceptance or unknown result | does not turn an earlier possibly-applied effect into failure | source |
| MATRIX-Q15 | capacity and shutdown | bounded admission/claims; pre-entry release; post-entry uncertainty retained | source; sustained host receipt required |
| MATRIX-Q16 | stale claim capability | token/attempt/lease mismatch cannot mutate current attempt | source |
| MATRIX-Q17 | network failures | DNS/TLS/connect/read/response-loss/5xx classification | source; platform fault receipt required |
| MATRIX-Q18 | edit target/content drift | same body with another replacement target produces a different signed binding | new Rust source; native execution required |
| MATRIX-Q19 | raw SDK bypass | no public raw client; real unsealed send performs no I/O; only opaque permit enters SDK | new facade/permit source; compiler and transport-negative qualification required |
| MATRIX-Q20 | pre-pin cancellation versus legacy unknown | new proven-pre-entry retry can first-pin; inherited unpinned attempts are durably unresolved and parked for authenticated reconciliation | migration-9/11 isolated tests passed; exact-head native execution required |
| MATRIX-Q21 | same-name schema weakening | content pin and store-open checks reject altered table/trigger DDL | source-complete exact schema validation; exact-head native execution required |
| MATRIX-Q22 | delayed echo after a newer retry claim | prior matching entered-use proof qualifies the stable transaction; current claim closes; reopen remains valid | migration-12 and native regression source; exact-head execution required |
| MATRIX-Q23 | grant expires or freshness changes after kernel entry | absolute grant expiry is checked after entered-use persistence and on every adapter poll; every post-entry fault remains the same transaction in `Indeterminate` and can never be released as pre-entry cancel/revoke | source plus closed-boundary unit regression; exact-head native execution required |

## 2. Qualification sources

`codex-rs/hepta-matrix-sdk/tests/durable_transport.rs`, `final_poll_regressions.rs` and `pending_poll_regressions.rs` retain sender/retry/fencing source cases, including delayed server echo after a newer retry claim but before its adapter entry. `codex-rs/hepta-matrix-sdk/src/outbound_v2/gate.rs` additionally binds the durable grant's absolute expiry through proof persistence and every transport poll; once kernel entry succeeds, persistence acknowledgement loss, expiry, revocation/frontier change, identity drift, payload drift or permit construction failure is returned only as an entered indeterminate result. New `src/content_tests.rs` and `authority_tests.rs` cover the version-2 message binding. `codex-rs/hepta-matrix-store/tests/content_binding.rs` adds reopen, pre-pin cancel, semantic drift, stale claim, malformed digest and weakened-schema cases. `scripts/tests/test_channel_matrix_legacy_remediation.py` exercises migration-11 ledger materialization, stale-claim closure, queue parking and the anti-reactivation trigger.

`codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs` and `tests/fixtures/run-hermetic-synapse.sh` retain the pinned unencrypted target profile. It records image/version/source/runner identity; storing it is not a successful run. Supervisor fixtures remain the lifecycle/adoption source. Migration-7 histories, migration-8 pins, migration-9 holds, migration-10 entered-use rows, migration-11 parking, migration-12 stable-transaction terminal guards and migration-13 recovery scheduling/quarantine are durable owner facts, not an independent sender or authorization issuer.

## 3. Executed-scenario receipts

```json
{
  "schema": "hepta.channel-matrix-qualification.v1",
  "scenario": "MATRIX-Q02",
  "candidate": {"commit": "...", "tree": "..."},
  "source_blobs": [{"path": "...", "git_blob": "...", "sha256": "..."}],
  "workflow": {"path": "...", "git_blob": "...", "run_id": "...", "job_id": "..."},
  "toolchain": {},
  "binary_digests": {},
  "homeserver": {"image": "...", "image_digest": "...", "version": "...", "git_sha": "..."},
  "configuration_sha256": "...",
  "failure_injection": {},
  "observed": {},
  "result": "pass|fail|skip",
  "artifact_manifest_sha256": "...",
  "authority_granted": false
}
```

Use this homeserver schema only for a real homeserver execution. Isolated schema/verifier tests must label their narrower scope, and have no homeserver identity, binary proof or production acceptance. Skips are not passes. Logs must be bounded/redacted and bound into an artifact manifest.

## 4. Exact-candidate lanes

1. Source head: verify exact source/map/document bytes, run Python guards, complete startup/migration tests, locked focused Rust tests, strict clippy, formatting and clean-source checks.
2. Deterministic merge: repeat applicable checks on the exact synthetic merge of the recorded base/source pair.
3. Hermetic Synapse: execute supported unencrypted transport, restart, ACK-loss and redaction cases on the pinned profile.
4. Encrypted target: authenticate and test real device/session rotation and transaction-scope continuity.
5. Restore/capacity: protected backup restore, sustained history pressure, rate limits and shutdown.
6. Independent acceptance: external operator/security review; never generator self-acceptance.

`sourceBase` is immutable provenance, not the current candidate. `observedAtHead` binds inspected Git objects, while `scripts/verify_channel_matrix_candidate.py --expected-sha "$TESTED_SHA"` emits the actual candidate/tree and file hashes. The validator rejects dirty inspected files, stale declared blob identities, path escapes, missing callsite markers and non-boolean/true production claims. These checks are static navigation, not an AST-level closed-world API proof.

## 5. Latest local and historical evidence

Across the preceding content-boundary increment, **27 isolated tests passed**: 13 migration-8 constraint tests, six migration-9 historical/new-work tests and eight temporary-Git verifier tests. This remediation increment adds five narrow synthetic SQLite tests for migration 11; they passed in the authoring harness but do not replace exact-candidate CI. The discovery command is:

```sh
python3 -m unittest discover -s scripts/tests -p 'test_channel_matrix*.py' -v
```

The local working fixture contained only those three new test modules, not the full repository or the older evidence-harness suite. CI uses the same pattern over the complete repository, so its test count will differ. Do not relabel the 27 local passes as a complete candidate pass.

Historical source-head run `36278075076`, candidate `b09690f5c25c6cf9c2e834335ee0db5097c5969e`, produced `PASS_CHANNEL_MATRIX_CANDIDATE_BINDING` but failed the locked focused command because Cargo.lock needed updating. The downloaded ZIP SHA-256 was `266b2826fc8f836bc458356309508a0f67cb4c942454e98488f9bf56f01c03c0`; all manifest file sizes and SHA-256 digests were checked. The focused log SHA-256 was `ae737da819d26367a569abded15de51c50843a60b117b0372dada0e507c9ef1e`, wrapper exit 102. This is a verified historical failure, not evidence for the new candidate.

## 6. Promotion rule

No product-execution, deployment, independent-acceptance, activation or release claim is granted by this increment. Keep `--locked`; commit only the pinned resolver's scoped lockfile result. The source now contains the kernel entered-use proof, durable authority/content binding, stable-transaction terminal qualification across retry attempts, exact whole-store startup validation and legacy-hold parking/reconciliation path, but those claims require passing exact-head and deterministic-merge native receipts. Real homeserver, encryption/rotation, restore/capacity and independent target profiles remain mandatory. A workflow file and local SQLite success cannot close those gates.

## 7. Typed sender optimization increment

See [OPTIMIZATION_CONTRACT.md](OPTIMIZATION_CONTRACT.md). Q23 retains its
post-entry uncertainty requirement. New JIT lease/cancellation and repeated-poll
measurement regressions are source fixtures, not executed native receipts.
Current CI separately runs locked all-target compilation, locked focused tests,
strict lint and owner formatting from `codex-rs`, preserving the pinned toolchain.
The evidence directory's generated `status.json`/`status.md` separates those
states from real target qualification and independent acceptance. Historical
local pass counts above apply only to their stated snapshots and test scopes.

## 8. Machine-checkable scenario ledger and new native regressions

`QUALIFICATION_SCENARIOS.json` is the current scenario-to-test inventory.
`scenario-ledger.json` is derived outside the checkout from exact candidate and
command receipts plus a hashed nextest JUnit report. Native binary+test identity
must match; compilation or aggregate test success cannot substitute for a case.
The registry is closed and ordered, and every scenario with a native test mapping
is a required exact-candidate gate—not only the newest recovery cases. Missing
reports, stale source/registry hashes, duplicate tests, XML DTDs, skips, flaky
retries and failed cases cannot yield an unqualified pass. The ledger records
the exact candidate, source snapshot, command receipt and JUnit artifact digest;
the later artifact manifest binds the ledger itself. External fields remain
`not_proved` even when native fixtures pass.

| ID | New required native fixture | Oracle |
|---|---|---|
| MATRIX-Q24 | presentation_extensions_reach_agent_as_plain_text_only | only plain text forwarded |
| MATRIX-Q25 | bad_event_is_delayed_durably_while_next_event_progresses | same identity deferred across reopen; good event advances |
| MATRIX-Q26 | budget_yields_without_canceling_or_reordering_identity | finish current event; next pass selects untouched event |
| MATRIX-Q27 | known_turn_projection_does_not_wait_for_slow_admission | output advances while unrelated bridge is blocked |
| MATRIX-Q28 | missing_turn_lookup_reconciles_only_its_existing_thread | no new submission from projection |
| MATRIX-Q29 | missing_core_identity_quarantines_without_losing_output_silently | explicit association failure; never silent success |

All six live in `codex-hepta-matrixd`'s `runtime::tests::recovery_tests` module.
They are source fixtures until the final exact-candidate JUnit proves execution.
The same ledger also requires every earlier registry-mapped native testcase;
external-only scenarios remain explicit target gates. Migration summary drift is
blocked by `test_channel_matrix_migrations.py`.
