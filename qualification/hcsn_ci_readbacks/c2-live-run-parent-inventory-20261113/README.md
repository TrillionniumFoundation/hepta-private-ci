# C2 live-run parent inventory — HOLD

Status: **HOLD_NO_GO**, `all_closed=false`, full independent training replay `0/6`.

This is a bounded, read-only inventory of the two historical native replay directories:

- `/home/qian-qi/hcsn-real-checkpoint-replay-20261112-c06d-run-v1`
- `/home/qian-qi/hcsn-real-checkpoint-replay-20261112-c06d-run-v2`

Both searches completed with full traversal of their selected directory, 16 entries each, and exactly six `.pt` results each. File metadata independently hashes every result. The v1 and v2 sets are byte-identical by fit and match the six later checkpoints already frozen by Draft #6305: epochs `116/76/126/50/127/72`.

None of the 12 paths matches the six required original campaign-v2 start-parent SHA256 values at epochs `46/47/46/47/46/46`. Therefore neither historical replay directory can supply the missing original parent bytes. The later checkpoints remain non-substitutable.

A separate broader content search under `/home/qian-qi` stopped at its declared 10,000-entry bound. It found no SHA-prefix match in the examined prefix, but coverage was incomplete. This evidence consequently makes **no whole-host absence claim** and does not replace external custody or a complete authorized storage inventory.

No model, Torch, optimizer, training, workflow rerun, job restart, threshold change, or production adoption occurred. The original controller terminal state, per-fit remaining-wall ledger, lifetime optimizer-call total, and the six start-parent bytes remain `UNKNOWN`/missing. Existing OOM, cancelled, RED, and UNKNOWN history is unchanged.

Run the standard-library consistency check with:

```sh
python3 qualification/hcsn_ci_readbacks/c2-live-run-parent-inventory-20261113/verify_inventory.py
```

This evidence does not admit or start full replay. Global status remains **HOLD / NoUpdate / all_closed=false**.
