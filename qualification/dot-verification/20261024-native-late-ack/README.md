# Late ACK after original-owner recovery

Parent #3687: c5e20892bda255f33b606a9069531ce0b56e4b06, tree 9459d3640ef389305e5d88513a608401e5af3813.

Coverage inventory: hepta-contracts provider journal already tests late dispatch ACK quarantine. The native AutomationStatusEffectOwner tests previously dropped a held future after recovery, never released it to return after the second owner settled. This finite addition tests that actual native/AutomationStore path, not another journal.

Two tests reuse the existing SQLite, final-use and file-provider fixtures. The first dispatch durably writes its controlled provider receipt, then waits for an explicit Notify. A second store connection looks up and settles the same attempt; the original TaskFlowTurnOwner commits that actual status. Full terminal receipt, Frame, cursor and history are saved before the first dispatch is released.

- Matching late ACK must return exactly the previously projected Completed status.
- Contradictory late ACK changes only the returned status to Rejected, not the persisted provider receipt or operation identity. The original ledger rejects different terminal kind/evidence; the native API reports its existing dispatch owner error. A timeout/panic is not accepted as this expected rejection.

Both actually await the released original future, assert full receipt/frame/cursor/history equality before and after, then close both connections and reopen to compare them again. Provider dispatch-entry count and lookup count stay exactly one. Existing modes and tests remain unchanged. No new schema/ledger or production implementation edits.

Contract basis: effect_dispatch_ledger.rs record_effect_dispatch_observation returns an identical existing observation, but rejects changed terminal kind/evidence; authorized_effect.rs provider_ack_digest includes key, payload, provider operation identity and ACK status. The test-only conflicting return intentionally violates the file provider's earlier completion, exercising fail-closed handling rather than claiming a real provider defect.

Scope: in-process current-thread async, finite controlled late returns; not exhaustive scheduling, multiprocess/power-loss recovery, real external provider behavior, or cancellation ACK qualification. No CI queries. No new product vulnerability is claimed unless an actual failing invariant is observed.

## Results

47/47 tests passed across the five selected integration targets, zero skipped/retried. Scoped no-deps strict Clippy passed, including a post-format run; formatting and diff check passed. The initial test source is retained for independent formatting comparison; no tests rerun after formatting per repository instructions. PTY dependency deprecation and nextest profile/metadata warnings remain visible. This is not a whole-workspace or all-features pass. No invariant failed and no production code was changed: this is a regression-coverage increment, not a newly fixed product vulnerability.
