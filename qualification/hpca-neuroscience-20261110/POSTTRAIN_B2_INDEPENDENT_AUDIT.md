# HPCA real CPU B2: retained two-choice decision collapse

**HOLD_NO_GO / DENY_ALL.** This independent read-only audit recalculates retained
real SmolLM2-135M-Instruct CPU two-choice probabilities. It does **not** run
new model inference, supply independent/withheld B, verify actual tool/ACT/CTRL
effects, or authorize production.

## Frozen identities

- Stack parent: V2 real LoRA PR #5905, exact commit 0ed4fce8bd07d361bf7eba40c40fe73d1f349c66.
- Original V2 training result SHA256: 9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c.
- Original 60-task manifest SHA256: 0f12ac4aa7fd32989ba62983ed82367b83fe6a3f51868e4c1b8f567a9decf12a.
- Original 540-row B2 result SHA256: 937a87f1da2e502f954be0870cd3a64ce06df0245938fc984b8b2a5ed0d95731.
- Original evaluator posttrain_probe.py SHA256: 3fad178df09fd0735353b01bcaf0ac86f3279b7b0a46ba548955e537ceafb5df.
- Original source retained on authorized ai395 at /home/qq/work/hpca-fresh-operator-b2-20261111/.
  The manifest/result are now preserved byte-identically here for independent hosted arithmetic replay.
- The manifest phase and timestamp are operator declarations, not independent evaluator custody.

## Recomputed real-output facts

Five arithmetic families, each with six yes and six no tasks. All sixty
operator-created tasks are reused across the frozen base and four paired
seeds (11,17,23,29) of interleaved/bursty actual trained LoRA adapters.

| Metric | Independent calculation from original rows |
| --- | --- |
| Actual retained scored model forwards | 9 x 60 = **540** |
| Two-choice prediction yes | **0 / 540** |
| Two-choice prediction no | **540 / 540** |
| Binary accuracy per run | **30 / 60 = 50%**, all nine |
| Bursty minus interleaved accuracy | **zero**, each paired seed |
| Paired Brier differences by seed | +0.0002509424, +0.0001726090, -0.0002130401, -0.0000421884 |
| Nine scoring process CPU times summed | 92.954481356 seconds |
| Nine scoring execution wall times summed | 24.313295296 seconds |
| Largest reported process peak RSS | 1,242,076 KiB |

The independent script checks all 540 task IDs, families, target labels,
probabilities, thresholded two-choice decisions, correctness, Brier score,
log-loss, aggregate/family metrics, source identities and complete paired
seed roster. It fails closed for forged yes, relabeled target, missing row,
missing seed, changed aggregate, changed manifest and ADOPT authority.
The JSON recalculation, original records, source and unit tests are retained
together; the hosted CI can repeat this arithmetic without model artifacts.

**Interpretation:** This is the operator-recorded two-choice scoring probe,
not a demonstration of open-ended generation outcomes. Since truth labels
are balanced, every run's 50% accuracy is also the constant-no baseline.
There is no observed binary task gain despite different LoRA parameters.
Four seeds and tiny, mixed-sign Brier differences do not establish
equivalence or an efficacy improvement.

## Scientific and production hold

There is no independent task curator, source/action/effect attestation,
future B, real ACT/CTRL business completion, seven-lineage controls, MEM
tombstone/retention validation, NDU 2x2, production NoUpdate/Adopt or
different next task C and Root/Agentd cold restoration. The reported CPU,
wall, and RSS are only the nine retained scoring processes, not whole-system
lifecycle resource cost (including training, network, energy and owner
recovery). Do not merge into a production authority path, adopt weights,
or claim independent efficacy from this evidence.
