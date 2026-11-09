# Frozen STOP-versus-continuation study runner

`metacontrol_study.py` accepts SHA-pinned train/calibration/future JSONL records
with explicit public state, source/context identities and evidence declarations.
The module's `EVIDENCE_FIELDS` and `ObservedContinuation` define the contract.
The source manifest, raw inputs, light table, all fixed-policy trials, checkpoint,
freeze and outcomes are retained. Future bytes are opened only after the
checkpoint, fixed action and light table have been saved.

Six policies share one experiment: STOP, trained public-context light table,
calibration-tuned fixed action, fully fitted point critic, unconditional residual
and finite-cell conditional residual. Only complete same-state observed action
tables yield replay returns. Unknown costs, absent counterfactual actions and
unsupported predictions remain null with their denominators retained.

Input execution cost must exclude policy planning. The runner adds each policy's
measured decision span times the declared tariff once. Mixed execution-cost
scopes are refused. Training, tuning, energy and provider costs remain unverified,
so even complete-declared input execution costs do not grant overall full cost.

```sh
PYTHONPATH=scripts:. python -m ndu_real_runtime.metacontrol_study --print-source-manifest
```

The CLI then requires all three file paths and SHA256 pins, a source manifest pin,
a new output directory and a latency tariff. Fixtures require `--allow-fixtures`.
READ/PREPARE then STOP cannot change delivered quality. READ plus an answering
suffix needs a separately declared and fully costed macro study.

The runner performs **offline observed-action replay**, not prospective native
policy evaluation. All seven study tests passed with the hardened checkpoint
contract. Results remain **HOLD_NO_GO / no-update**.
