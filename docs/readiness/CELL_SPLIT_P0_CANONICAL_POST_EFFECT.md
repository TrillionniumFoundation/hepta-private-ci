# P0 canonical original-owner post-effect Selector/NDU fence

**Scope:** unmerged draft extension of the original 4-effect, single-writer, FD-pinned
`CellSplitExecutionOwnerV1` from PR #2597 at `903045190798ba2adfec0a5a12243cd97fb9578c`.
This adds no new physical execution service or independent authority.

The original coordinator already checks independently admitted selection twice
before the fsynced Prepare and rejects stale, tampered and unauthenticated
original effect receipts. Its last predecessor readback can be followed by a
long-running native CAS/migration/CNS/Supervisor effect. A selection may be
withdrawn while that effect is committing. Before this change the local
coordinator could append the `committed` frame after that revocation.

After a real native effect and signed current-owner readback, the coordinator now:

1. Revalidates the original, immutable local ledger and native predecessor
   receipts.
2. Queries current Selector/NDU admission again; denial is **Ambiguous**
   because the native effect may have committed, not a safe negative Execute.
3. Revalidates the original locked plan, keys, prepared intent and prefix after
   the admission callback. If anything changed, leave Prepare unresolved.
4. Only then attempts fsynced, create-only local Commit.

When either post-effect gate rejects, cold recovery reopens the same exact
prepared intent and read-only reconciles with the original signed effect.
It never dispatches another Execute for that idempotency key. Tests cover all
four real-operation stages with fixture native signers, native-readback-triggered
revocation, and local post-callback trust substitution.

**Not a physical transaction:** this is a coordinator ACK fence, not an
atomic distributed Final-use grant, remote generation fence, native CAS/CNS
commit, independently stored rollback floor or independent observer. The
external owner must separately enforce Final-use at the actual effect boundary.
The native test signers are fixtures and are not production issuance.

**Exact-source qualification required:**
```bash
cd codex-rs
cargo test --locked -p codex-hepta-operator-acceptance --lib post_effect_
cargo test --locked -p codex-hepta-operator-acceptance --lib selector_withdrawal_during_post_effect_
cargo fmt --all -- --check
cargo clippy --locked -p codex-hepta-operator-acceptance --all-targets -- -D warnings
```

Keep DRAFT / DENY_ALL until the canonical P0 source-head and merge tests,
B4, global blocking CI, independently signed original effects and target-host
crash/power-loss gates all succeed. Do **not** merge or activate the separate
Supervisor readback seam in #2621/#2663 as a second production executor.

## Canonical Control ancestry and final operator readback

The original canonical Control WAL orphan inspector branch PR #2642
(`f4a688592a0102f82dfe086b2b2c9f7c5224e89f`) is adopted as a **second Git parent** of the
post-effect fix. The merge retains the same original Supervisor/CNS/Artifact
owners and the independent immutable Control actor; its orphan-`Begin`
readback remains **read-only** and cannot invent Control Commit, unfreeze a
physical owner, or authorize a new Execute.

The legacy operator CLI was also hardened: a four-owner `verified_complete`
readback is not permission to return `complete=true` if the current NDU
selection was withdrawn during that last RPC. The final status callback is
read-only, has no promotion authority and cannot replace native Final-use.
Transcript-mode output is historical, `production_activation_authorized=false`.
Both the original execution-owner and CLI code remain blocked from production
physical CellSplit.

Added a focused `post_readback_selection_withdrawal_cannot_report_completed_split`
regression and updated exact-head expectations. The Control orphan inspector
tests observed green at the original #2642 SHA do not automatically qualify
this merged source SHA.