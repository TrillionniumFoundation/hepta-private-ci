# Redacted physical Granite evidence handoff (RESEARCH / DENY_ALL)

## What was wrong

The original *"never weights/texts"* upload step included `granite-q24-features.json`,
`*-trial-panel.json`, and `*-trial-report.json` / `*-hard-train-report.json`.
Those raw files can hold the original per-case labels and feature vectors and
actual FP32 trained Head parameters. A GitHub Actions artifact is a separate
publication boundary from the ephemeral Runner process that executes the
independent numeric evaluators. The upload path should not silently disclose
raw research inputs or learned weights just because the source corpus is public.

## Correct boundary

`physical_router_safe_export.py` runs **after** the original model/data checks,
all physical Head training, numeric/route/OS cost replays and five-arm/paired
summaries. Original files stay in `$RUNNER_TEMP/hepta-meta-real` while their
trusted-by-the-job consumer uses them. The exporter reads a bounded,
non-symlink, exact expected file inventory, hashes each input, validates the
pinned original public-source digest, and validates two known aggregate report
schemas with **both** complete 3-seed × 4-original-arm inventories.

The only published file is
`$RUNNER_TEMP/hepta-meta-redacted/granite-redacted-receipt.json`. It contains:

- fixed names, SHA-256 digests and sizes of expected original research files
  (no bytes, per-case identifiers, features or FP32 weights);
- sanitized per-seed aggregate accuracy/Brier and operation counts for all
  **five** policies (including genuinely frozen No-Change), with five-arm OS
  CPU/RSS medians (including Python/Torch startup and replay);
- explicit blocked/no-authority/no-prospective/no-OOD/no-cost-parity flags;
- missing-entry / invalid-schema reasons if the physical run failed partway.

The exporter runs even after failure. It writes a **create-only** bounded receipt
before returning exit code `2` for an incomplete, malformed or unsafe inventory.
The separate upload step runs `always()` but cannot fall back to raw inputs;
when no redacted receipt exists, artifact upload itself fails. Duplicate keys,
nonfinite values, tampered control flags, omitted seeds/arms, symlinks, FIFOs,
unexpected filenames, oversized records, and changed data during read reject.
The scalar serializer constructs new typed objects: it does **not** pass through
unknown report fields, raw text, scores outside [0,1], tensor dumps or arbitrary
strings from model outputs. Its exact artifact allowlist is protected by a
workflow-source regression test.

### Consequences and acceptance limits

Hashes preserve *claims of source identity*, not the source bytes. Subsequent
third-party, bit-exact replay is impossible from this public artifact **alone**.
If the operator needs raw re-verification, a separately approved private,
independently signed and access-controlled custody mechanism must retain the
original files; there is no such mechanism in this research PR. Do not create
an unsigned replacement artifact or auto-promote the result to an NDU gate.

Even `COMPLETE_DESCRIPTIVE_ONLY` is a **syntactic observation of a self-declared
job**. The job is not a signer or independent Evaluator: the sample source is
retrospective, repeated seeds are correlated, the original model weight origin
is not independently authenticated, energy/target-host/complete compute and
prospective NDU are not demonstrated, and physical Cell Split / FinalUse remain
`BLOCKED` / `DENY_ALL`. This change does not alter any Rust production owner,
source, dependency, selection, model weights, or `main` branch.

Run the stdlib-only tests from repository root:

```sh
python -m unittest -v \
  qualification.cell_meta_execution_af.physical_router_safe_export_tests
```
