# Durable training evidence and post-seal action-menu bounds

Base: `fce2e8eae2fdc9bd98f3f887b6d6a86157a2d643`, PR #1546.
No default policy, search weights, price, task split, Riccati or Rust NDU changes.
Existing resumable-search work is retained, not duplicated or claimed as new here.

## Completed hosted evidence, distinct from this patch

The repaired budget run **38202685803**, source
`b7ecedff22311b3af7dea76696d20287ac732352`, completed **1536/1536** episodes with
zero execution failures. Artifact **11725619948**, 389149 bytes, ZIP SHA256
`0c8744c715d4a828224a45c18936583d947b2b2dc6b33f264b597ea139f451f0`.
All **31 manifest entries** and the prediction seal were checked locally. The
original critic archive 11724608246 also passed all **27** manifest checks.
Hosted regression log: **1130 passed, two skipped, 1132 total**. Static checks
passed after removal of the unused import; the earlier failed run is not a pass.

| Next 48 tasks | Direct heuristic proofs / mean utility | Learned gate | Perfect restart-menu envelope |
| --- | --- | --- | --- |
| 256 successors | 34 / 0.693010417 | 30 / 0.606485417 | 30 / 0.613685417 |
| 1024 successors | 41 / 0.826864583 | 39 / 0.777877083 | 40 / 0.812839583 |

At 1024, the observed direct-minus-learned utility gap decomposes into
**0.014025** between direct and the perfect restart menu, plus **0.0349625**
between that menu and the learned selector. The existing restart menu loses
`(1,3,4,6)` even under perfect selection. This is a statement about THESE
observed actions and tasks, not a theorem excluding other algorithms or domains.
At 256 it structurally loses four direct successes. On the prior 48 tasks at
1024 the menu does have positive average headroom; do not generalize the next-48
negative result to every slice. These are reused synthetic tasks, not new natural
language or multimodal evidence.

## Durable training collection

Previously the caller wrote training rollouts only after `collect_training`
returned; a second-tail exception could discard an already completed probe and
first tail. The collector now accepts an empty caller-owned ledger and a callback
receiving detached events. It emits context and child-start events before work,
then completion/failure events. The runner appends, flushes and fsyncs these events.
Its `finally` block writes the partial rollout snapshot and planned-context census.
Ordinary exceptions and interrupts are re-raised, never converted to negative
training labels. A failed log write prevents further unjournaled training work.

The census reports completed child work only as a known lower bound. Missing,
failed, and not-yet-started work are explicit; they are not zero-cost successes.
A killed process can leave an in-flight start event. Filesystem/hardware failure
can still prevent persistence; this is not an unconditional crash-durability claim.
Successful probes remain recorded even when no continuation examples exist.

## Post-seal menu audit

`system2_budget_audit.py` validates planned question/arm identity, raw proofs,
child-to-episode accounting, paired probe equality and equality between the
chosen frozen action and its fixed-control run. It then computes per-question
maximum observed utility across `probe_stop`, `probe_heuristic`, `probe_value`.
It reports menu-minus-direct and selector-regret intervals separately, preserving
all planned questions when a row is missing or failed. Failed known budget
overshoots invalidate the registered bounded analysis rather than receiving a
false finite certificate. Other unknown bounds assume the registered work cap.

This is a perfect-information diagnostic, NOT an online policy, a confidence
interval, or a global solution bound. It runs after the prediction seal and has
no model/search/oracle call. The existing resumable-search ceiling report remains
unchanged. No evaluation outcomes feed controller training or action selection.

## Local qualification and reproduction

**35/35** focused tests passed (16 existing and 19 added). They include real runner
failure persistence, an interrupted child, logging failure, snapshot isolation,
missing-arm bounds, invalid proof/work/probe rejection and no-oracle audit checks.
The exact dependency source slice under Python 3.13.5 / torch 2.10.0+cpu completed
both the unmodified and patched **1536-episode** runs. Excluding timing, all
predictions, actions and work receipts are identical. Both fitted tensor files,
training features/targets and freeze receipts are byte-identical locally.
This is not a full-repository or pinned torch 2.5.1 pass.

The patched run recorded 24 planned/completed training contexts, 14 usable return
targets, 52 actual child rollouts and 10725 generated successors, including both
counterfactual tails. It wrote 152 durable training events. These calls were for
local regression validation, not new independent task evidence. The archive-only
menu audit invoked no new model. Compilation, YAML parsing and patch checks pass.
`just fmt` was attempted but the command is absent; local Ruff is unavailable.
The hosted workflow preserves all regressions, static gates, original budget trial
and resumption comparisons, and adds the new files to scoped lint/artifact capture.

```sh
python -m unittest discover -s scripts/memory_cell -p 'test_system2_budget*.py' -v
python scripts/memory_cell/system2_budget_audit.py completed.zip new-report.json \
  --sha256 0c8744c715d4a828224a45c18936583d947b2b2dc6b33f264b597ea139f451f0 \
  --source b7ecedff22311b3af7dea76696d20287ac732352
```

No new controller superiority, calibrated probabilities, language capability,
FBSDE correctness beyond prior special cases, or production acceptance is claimed.
