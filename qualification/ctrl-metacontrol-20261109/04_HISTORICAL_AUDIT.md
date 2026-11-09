# CTRL 4: pinned historical content audit

The audit consumes original trajectory, launcher, snapshot and evaluator files
through an exact-byte, SHA-256-pinned manifest. It emits digest-only identities
and distinguishes the first evidence inconsistency from the first unknown link.
Legacy missing selection evidence is unknown, never an invented failed action.
Repeated case IDs are allowed for distinct episodes; duplicate artifact pairs
are rejected. Owner authentication is a separate required step.

```sh
PYTHONPATH=scripts:. python -m ndu_real_runtime.content_audit \
  --root /trusted/raw-artifacts --manifest /trusted/manifest.json \
  --expected-manifest-sha256 EXPECTED_SHA256 --output /new/audit.json
```

The manifest schema is `ndu.real.content-audit-manifest.v1`; the module specifies
the exact fields. Optional reference diagnostics require source and normalizer
pins and allow only train/development/retention-validation roles. Missing text
quality remains unknown. References and candidate texts are not emitted.

Six fixture tests and a separate code review passed. Raw-wire inconsistency may
mean missing or mismatched exchanges, not necessarily corrupted payload bytes.
Original #5450 raw artifacts have not been recovered, so its six zero-score
WRITE_TEXT episodes still have **unestablished root cause**. **HOLD / no-update**.
