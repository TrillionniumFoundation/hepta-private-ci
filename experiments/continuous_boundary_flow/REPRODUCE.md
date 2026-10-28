# Reproduce the published continuous-boundary evidence

Start with the repository branch `research/continuous-boundary-flow-20261028`.
The Python audit and evidence extraction need the versions in this directory's
`requirements.txt`; they do not require compiling the native host.

The readable conclusion is `REPORT.zh.md`. `results/RESULTS.md` and
`results/SUMMARY.json` contain the machine-generated report, and
`results/AUDIT_SUMMARY.json`, `NUMERIC_AGGREGATES.json`, and `OWNER_SUMMARY.json`
provide independent verification summaries.

## Complete evidence

`evidence/bundle/INDEX.json` binds all archive and file-manifest parts. Each
published part is at most 480,000 bytes. Extraction verifies every part, whole
archive, and restored file, rejects links/path traversal/duplicate members,
and requires a new output directory.

From the repository root:

```sh
python -m experiments.continuous_boundary_flow.evidence_bundle unpack \
  --bundle-dir experiments/continuous_boundary_flow/evidence/bundle \
  --output-dir /tmp/hepta-boundary-restored
```

The restored layout is:

- `study/`: original protocol, source/environment/selection seals, all training
  datasets and 1,728 candidate profiles, chosen checkpoints, 208 confirmation
  shards covering 26,624 episodes, original costs, and the preserved aborted
  training-only run in `history/study-001/`.
- `study/analysis/`: canonical reports, numerical diagnostics, original and
  derived audit receipts, and the unique files defining the cost audit view.
- `engineering/`: all 96 durable owner tasks, full task checkpoints, journals,
  witnesses, cold-recovery outputs, raw traces and process receipts.

The archive preserves the original `study/manifest.json` and `costs.jsonl`.
The original strict audit rejects 153 tiny negative child-CPU differences.
It is not represented as a passing original audit.

## Recreate the explicit cost audit view

The following helper first runs the **unchanged frozen auditor** on the
original bundle and retains its actual result. Only the specific child-CPU
negative-zero error permits creation of a separate view. It changes only
negative top-level `completed_child_cpu_seconds` values in `[-1e-12,0)` to
`0.0`; the original files remain intact. It independently verifies the exact
whitelisted byte transformation before rerunning the same auditor on the view.

```sh
python -m experiments.continuous_boundary_flow.cost_audit_view run \
  /tmp/hepta-boundary-restored/study \
  /tmp/hepta-boundary-audit-view \
  --receipt-dir /tmp/hepta-boundary-audit-receipts

python -m experiments.continuous_boundary_flow.cost_audit_view validate \
  /tmp/hepta-boundary-restored/study \
  /tmp/hepta-boundary-audit-view
```

Expected published status: `original_rejected_derived_passed`, with 153
corrections totaling `8.2822203956167681423E-14` seconds, 2,154 other input files
byte-identical, 26,624 audited episodes, 205,470 verified native/deadline steps,
and zero of three primary benefit gates passed. No episode, score, model,
protocol, seed or statistical threshold is changed.

## Regenerate the report

The reporter verifies the original/derived manifest chain and the engineering
study's original manifest identity. It writes outside both the original study
and the audit view:

```sh
python -m experiments.continuous_boundary_flow.reporting \
  /tmp/hepta-boundary-audit-view \
  --original-run /tmp/hepta-boundary-restored/study \
  --audit-receipts /tmp/hepta-boundary-audit-receipts \
  --engineering /tmp/hepta-boundary-restored/engineering/SUMMARY.json \
  --amendment experiments/continuous_boundary_flow/preflight/DEADLINE_AMENDMENT.json \
  --output /tmp/hepta-boundary-report
```

Absolute paths in provenance receipts will reflect the local reproduction.
The original published reports and complete receipts remain in the archive.
The three registered comparisons must remain the primary inference; descriptive
bootstrap results must not replace the simultaneous paired-seed t intervals.

## Recompute the independent numerical diagnosis

```sh
python -m experiments.continuous_boundary_flow.numeric_robustness \
  --study-dir /tmp/hepta-boundary-restored/study \
  --output-dir /tmp/hepta-boundary-numerics \
  --confirmation-complete
```

This reuses the exact 128 saved contexts and existing records. It neither
creates new confirmation samples nor refits policies. It compares four grids/
generators and reports state occupancy plus its own analysis costs. The default
model is a discretized task, not an exact continuous-time ground truth.

## Rebuild and rerun native research

See `native/README.md` and the parent `README.md` for the exact pinned Rust
source/dependency builder and full study CLI. The original scientific core was
sealed at commit `5bbd4f254f9331227e3b3acb048ae3e6a422ee4b`; all selected model
identities were published at `d7af4cba57bb7d5472c0794d4f09c31ec98e1787`
before confirmation existed. The original final native binary SHA-256 is:

```text
1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5
```

Any new training/evaluation run must use a fresh output directory and record
its own environment, source and binary identities. A numerical reproduction
is separate from the original evidence. Retain the original eight-seed study;
do not append seeds until a desired significance result is obtained.
