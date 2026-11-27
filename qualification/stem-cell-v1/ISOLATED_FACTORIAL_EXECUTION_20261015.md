# Hepta Group 2×2 isolated OS process experiment

Date: 2026-10-15. **DRAFT · SHADOW_ONLY · DENY_ALL.**

## Concrete execution correctness issue addressed

The earlier 2×2 physical experiment (PR #2367) used a Python process that
called `group_attention_campaign.run(...)` four times in sequence. It
therefore paid four logical Encoder loads but shared one Python/PyTorch
allocator, import runtime, cache/garbage collector and process lifetime.
This is insufficient to isolate cold-start, memory residency and training
CPU use across its legacy/guarded × verifier/no-verifier conditions.

It did not prove four independent operating-system processes. Its
original source commit and pending workflow remain unchanged and may be
evaluated on their original merits.

## This child runs real operating-system process isolation

`group_factorial_process_driver.py` validates the immutable source-local
campaign and original pure-stdlib independent reviewer files, then starts
each of the following as a *separate* executable Python OS process:

| Actual original arm | TRAIN terminal labels | TRAIN answer-dependent Verifier |
| --- | --- | --- |
| legacy_oracle | every step | enabled |
| legacy_no_verifier | every step | disabled |
| guarded_oracle | only once required evidence is reached | enabled |
| guarded_no_verifier | only once required evidence is reached | disabled |

The same immutable approved local Granite97 checkpoint directory is used
across all four; **each model is physically reloaded into its own process**.
The four child processes do not share Python allocator, live Tensor objects,
optimizer state or in-memory feature cache. Each child has a wall deadline,
private process group, observed PID, exit code, waited child CPU, log-byte
SHA-256 and full per-arm original model report digest.

A **fifth separate Python process**, running with `-S`, reopens original
source/teacher/task/checkpoint/trace data through the established full
`group_feedback_factorial_review.py` independent audit. The research
driver refuses incomplete/failed/timeout runs or any original report without
explicit `DENY_ALL` and no-production posture. No false source/model
origin, physical power/RSS reduction or independent host attestation is
claimed. The per-arm process CPU is observed rather than a host-certified
cgroup total; it must not be added to online nested CPU measurements twice.

### Executable entry

```sh
python -S qualification/stem-cell-v1/group_factorial_process_driver.py \
  --snapshot /approved/granite97 \
  --output-root /sealed/os-isolated-2x2-41-sgd \
  --seed 41 --steps 120 --train-count 256 --heldout-count 96 \
  --training-profile sgd_v1 --timeout-seconds 2700

# An independently executed second pass on all four preserved original arms.
python -S qualification/stem-cell-v1/group_feedback_factorial_review.py \
  --legacy-oracle /sealed/os-isolated-2x2-41-sgd/legacy_oracle \
  --legacy-no-verifier /sealed/os-isolated-2x2-41-sgd/legacy_no_verifier \
  --guarded-oracle /sealed/os-isolated-2x2-41-sgd/guarded_oracle \
  --guarded-no-verifier /sealed/os-isolated-2x2-41-sgd/guarded_no_verifier \
  --output /sealed/os-isolated-2x2-41-sgd/external-recheck.json
```

The branch-specific research-only workflow
`.github/workflows/hepta-group-factorial-isolated.yml` first executes
actual OS-process negative tests, then attempts six independent CPU hosted
jobs (seeds 41/47/53 × SGD/Adam), each with four isolated processes and
a separately executed fifth independent reviewer. A queued or canceled
job is *not* a successful pretrained study.

Only bounded research JSON receipts and Group safetensors are archived,
**not** the frozen foundation Encoder weights, raw inputs or live model
memory. The original production `main`, selected Stem, Cell owner, NDU
effect boundary, Control/CNS, Worker/FinalUse and WAL/CAS remain untouched.

## Evidence actually executed

The exact code from the GitHub commit was materialized into an isolated
Linux container and checked with original Git blob hashes:

- `group_factorial_process_driver.py` **9014e7f214328bc265f54f6edb064cd47c696601**
- `test_group_factorial_process_driver.py` **da0ba622eddac4fd189034c0858fdbdc57ec3e9a**

A real subprocess test initially exposed an incorrect PID access in the
new driver (`review.pid` instead of the dictionary receipt
`review["pid"]`). This was corrected **before** qualifying results.

Six distinct real-process fault tests then **passed 6/6 normally and 6/6
under `python -O`**, verifying:
- four distinct actual Python process IDs and an independent fifth
  reviewer PID;
- successful source/report digest and DENY_ALL output;
- source/optimizer/guard pairing and actual waited CPU/wall receipt;
- original training child nonzero exit rejection;
- timeout cleanup of an isolated process group;
- invalid independent final review denial;
- symlink/duplicate-output/invalid-budget denial before training.

These tests used lightweight scripts instead of authentic Granite97 model
weights. They prove OS-process execution and failure mechanics, **not**
learning quality, actual 24-run completion or independent full host cost.
Real-weight and future source-disjoint task outcomes remain pending.

**DRAFT / DENY_ALL / NO AUTOMATIC CELL SPLIT / NO MAIN MERGE.**
