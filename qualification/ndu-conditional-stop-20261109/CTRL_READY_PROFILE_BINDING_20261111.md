# CTRL readiness-profile admission: bounded red/green verification (2026-11-11)

**Disposition: HOLD_NO_GO / NoUpdate / Draft.** This is a research-only source/receipt consistency hardening. It does not certify an original owner, policy quality, production authority, or the reason why the six historical WRITE_TEXT payloads were wrong.

## Frozen dependency and original reproduction

Parent: [CTRL #5963](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5963) at `9f8ddd5684fa023dec8944bf2832d8b2274a2491`. The untouched parent was independently materialized on configured HeptaRuntime operator `ai395`. The nine transferred source files were checked using `git hash-object` against their corresponding GitHub blobs; no cloning of the 11 GB repository or dependency substitution was claimed.

- Baseline original historical audit suite: **8/8 passed**, no skips.
- RED actor-profile probe: both (a) an initial ready with no `content_identity_profile` and (b) an initial ready with `unrecognized-profile.v1` produced **selected_used=true** in both the historical `audit()` row and the native `content_identity_report()` row. The synthetic actor action, candidate inventory/receipt, wire and host-exchange digests, delivery and evaluation were all otherwise consistent.
- Original bounded execution ID: `1a1ca71aeb7-2564-5eb`, terminal succeeded on `ai395`. This is a manufactured self-consistency acceptance-boundary counterexample, **not** evidence that the actual source-owner actor was bypassed.

## Minimal change

1. Preserve `candidate_selection` as the independent structural-hash check.
2. Add `selection_profile_advertised` to the posthoc chain checks: a structurally valid witness without an initial ready declaration of the exact `ndu.real.content-selection.v1` profile is **not** a positive selected-use observation. A ready declaring an unsupported profile also fails the wire protocol check.
3. At the native identity report boundary, reject unsupported ready profiles and reject a selected WRITE_TEXT witness when initial ready did not advertise its receipt contract. True legacy missing-selection records keep `selected_used=null`; properly declared matching receipts remain accepted.

No actor, model weights, scorer, training, policy, production owner, or persisted originals changed.

## Scoped verification

HeptaRuntime `ai395` corrected candidate job `1a1ca75b88c-2564-606` completed with exit 0:
- **9/9** historical/identity Python tests passed, including new four-case missing/unsupported/valid/legacy regression; no skips.
- All three altered Python files passed Python `compileall`.
- Independently checked tested Git blob IDs:
  - `scripts/ndu_real_runtime/content_audit.py`: `bc4db8c9215b998cb64f8d2eb685d92d15f99fa3`, SHA-256 `883088ef1cb45c5c44cd3f3c24209c8276cb32ff4992f66ac69c35957d811816`.
  - `scripts/ndu_real_runtime/content_identity.py`: `4d1bde6e43ee9ba158b48425224051e65e755a07`, SHA-256 `abaf08f2e0e17fc34b96e779adc8b58ea04e80cfd24c0733e11b0bfb4937076a`.
  - `scripts/ndu_real_runtime/test_content_audit.py`: `c217c0319c83362e8da9307a0f31e26502044eb0`, SHA-256 `2a3d327fb74fa3727f298df80ae0aff64a97d3edf56f1f53261dd967deaa445c`.

For completeness, the first patched attempt `1a1ca74690a-2564-5fc` **failed** because the new test's newline escaping was incorrect and a candidate check initially conflated witness validity and readiness qualification; both defects were corrected before the final successful run. The initial failure is not counted as scientific evidence.

## Open gates

The full native heavy-dependency suite and fresh exact-head CI are **NOT_RUN** here; `ai395` system Python lacks NumPy and Torch. No complete original actor recapture, target-selected-index provenance, independent B evaluation, matched STOP vs continuation, action realization calibration, paid READ/VERIFY/REPAIR, strong light/fixed full-cost comparison, actual owner admission, deployment, or merge was executed. None of these gates is inferred from a digest-only report.
