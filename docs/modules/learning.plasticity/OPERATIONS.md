# learning.plasticity operations compatibility entry

The current operating profile, stop thresholds, rollback/fence model, recovery runbook
and qualification boundary now live in
[`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md#9-operations-and-observability-profile).

This stable path is retained for existing links. It intentionally does not duplicate
current-source facts. Machine-readable current-vs-target status lives in
[`CURRENT_STATE.json`](CURRENT_STATE.json), and its projection is verified by:

```text
python3 scripts/hepta-plasticity-status.py verify
```

The stable target/development design remains
[`TECHNICAL.md`](TECHNICAL.md). None of these documents grants parameter installation,
runtime topology mutation, selection, activation, promotion or release authority.
