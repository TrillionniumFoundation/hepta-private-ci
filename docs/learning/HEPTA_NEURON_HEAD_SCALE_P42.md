# P42 — physically allocated pretrained-Encoder task-Head CPU scale probes

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** This is an exact child of
P41 [#3445](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3445)
at `4b672808ceaa13597d7792201e06a82e0819b750`. No main or
ancestor modification, no production authority, no model/Cell Split promotion.

## Physical question answered by this probe

P39 executes original Arctic 305M / Harrier 270M Encoder checkpoint tensors,
trains a task-only linear Head with 200 AdamW steps, and retains raw held-out
predictions from exactly five eight-row diagnostic cohorts. That does *not*
demonstrate resource growth across 4096 private Heads. P37's existing
`real_head_fanout.py` physically allocates 4096 trained private Head replicas
for other models, but records only three fanout latency samples.

The new `replacement_head_scale.measure_trained_head_fanout` uses an actual
frozen Encoder feature computed earlier in P39's run and that same run's
original trained task Head. For each fixed scale **64, 256, 1024, 4096**:

- Deep-copy the Head into *physically distinct* Python/Torch modules and
  reject any parameter-storage aliasing with the original or peers.
- Require the real trained Head's frozen evaluation state, source feature
  shape/dtype/finite values, and a single unchanged source-feature SHA256.
- Execute two unrecorded warmups, then **100 timed complete fanout batches**,
  each invoking every private Head in sequence. Preserve all 100 raw latencies,
  recomputable p50 / nearest-rank p95 and p99, output throughput, tensor bytes,
  observed process RSS and Linux process high-water RSS.
- Fail on nonfinite/wrong-shaped outputs and report all physical observations
  without invented GPU or simultaneous input claims. The real Encoder is
  instrumented by a post-encoding forward hook to ensure zero new Encoder
  calls from fanout.
- Retain the entire non-authorizing profile in each Arctic/Harrier
  `physical-output.json`, preserving P39's original weight/row receipts.
  The independent-format `replacement_physical_audit.py` rescales and
  recomputes all 100-sample metrics, rejects claims of 4096 simultaneous
  inference, missing timing samples, aliased Heads and fake resource receipts.
  The three Laya arms continue to run the *complete Laya policy* and must
  not claim these new external task-Head results.

Run on the branch's original-weight GitHub Actions five-model physical
CPU matrix. Focused source contract tests are in
`test_replacement_head_scale.py`, plus new cross-arm audit negatives. No
synthetic or test-derived timing may be reported as real model results.

## Explicit limits and remaining six-stage blockers

This proves a narrow **single preencoded source event, 4096 separate private
task-Head allocations evaluated sequentially** profile on one CPU host *only
when the original-weight CI matrix actually runs and stores matching source-
bound artifacts*. It does **not** prove that 4096 Cells were independently
trained, ran 4096 distinct simultaneous question-conditioned Encoder forwards,
were concurrently scheduled, have production CPU/GPU p99, or consumed a
measured amount of energy. 100 samples support diagnostic tail statistics,
not strong p99 confidence or target-host SLO admission.

P42 adds no prospective multilingual/retrieval cohort, independent full-policy
equal-budget fine-tuning, statistically sufficient calibration/OOD/negative
transfer, installed target device, or independent signed Artifact CAS / CNS
cutover / checkpoint migration / generation fence / crash / rollback /
old-generation Final-use denial.

All six production acceptance stages **remain OPEN** until independent
operator observation and exact-current-head CI succeed. Any original-model
incompatibility must fail rather than substitute an unpinned model.
