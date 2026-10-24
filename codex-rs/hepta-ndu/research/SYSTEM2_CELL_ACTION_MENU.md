# System2 Cell action-menu ceiling: stop investing where oracle headroom is zero

Research-only, stacked under [PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546). The exact Reader/Encoder inventories, Qwen weights, NDU/FBSDE, Riccati, pretrained inference and production default are **unchanged**. This is a read-only retrospective study; it does not create model outputs or claim to save CPU work previously paid.

## Why this experiment, now

The preceding six-scalar Cell-gate experiment passed its **hosted** regression and Ruff checks: [38350846827](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38350846827), original-archive artifact 11791230966, external SHA256 `e2ba45d89995d2720f63a9926fa497c15d7d7e6c67ae7394a34f0f9d31e316e9`. The *learned* gate chose exactly the same 200 actions as a **zero-training, fixed exact source-match** rule. Both were 121/200 correct across correlated synthetic task/action conditions. Always call scored 61/200; always abstain 80/200. The 80 hypothetical avoided prior Qwen calls were all actually executed historically.

This raises a decisive question: is there **any** theoretical room for a more powerful Head when its only permitted choices are (A) call the same frozen Reader on the same registered source rendering or (B) abstain externally?

## Exhaustive but restricted hindsight analysis

This new module verifies the three original external archive SHA256 pins, every internal manifest entry, exact generating commit and tree, sealed model raw answers, original pre-model input seal, question/start/answer identifiers, Reader identity, and exact source bytes through the unchanged `system2_cell_support_gate.prepare` loader. Cohorts are unchanged: 40 previously exposed training synthetic device-code identities and 20 previously exposed evaluation identities; 200 evaluation positions in ten registered evidence/source presentations.

Before scoring, it projects only question/device identity, visible source relation facts, source count and registered action identifiers; it **omits the gold target, original Reader answer, and decoder CPU**. It writes and SHA256-seals exactly 200 deterministic decisions:

- The prior frozen no-training policy calls Reader iff exactly one original source fact matches the question device; otherwise it returns external abstention.
- A separate, **fully symbolic** control extracts the answer code directly from that same strict closed grammar, or abstains if no matching fact exists. This is **not** a neural Cell or general-purpose semantic verifier.

Only after the seal does the audit compute, for each position, whether `call` would have produced the original exact answer and whether `stop` would correctly abstain. The perfect-information per-position menu is **max(call correct, stop correct)**. There are no other policy actions in this particular bound. A supported task cannot become correct merely by stopping, and an unsupported task can always be correctly stopped. Accordingly the frozen exact-match policy must equal this restricted menu ceiling **by construction**. The run checks this equality against all actual archived responses. It does *not* establish an upper bound on all possible search/Reader architectures.

A second separately labeled hindsight study enumerates the **three already paid** Reader rendering views (`e_label`, `neutral_alias`, `unlabeled`) for each of 40 source-sufficient question/source-order cases. Report:

1. A fixed, preregistered one-call `unlabeled` view.
2. The hindsight best-of-three upper envelope (one uses original answers/gold **after** the seal).
3. The number of cases where another rendering, already in the historical archive, would repair the fixed-view failure.
4. Original decoder CPU for the fixed view versus all three views. **The hindsight identity of the winning view was unknown at request time and cannot be chosen for free.**

The audit also computes closed-grammar parser correctness without charging any symbolic success to the Qwen Reader. Any synthetic 200/200 outcome from that parser is not evidence of a learning gain; it shows that this exact grammar does not require a pretrained Reader at all.

## Strict evidence and non-claims

- The frozen archive pins remain the original **320-call lexical**, **180-call TAG representation**, and **200-call equal-token label-placebo** ZIPs. No new model data, retrieval labels or Reader outputs are invented.
- Complete 200 positions or fail; no unavailable answer is treated as a successful abstention or free inference.
- All original 200 Qwen decoder CPU receipts are **historical paid work**, whether the replay policy would have called or not. A replay cannot retroactively save GPU/CPU time.
- No statistical confidence, independent natural-language adequacy, semantic citation quality or parameter-to-10T/100T equivalence follows from 20 correlated synthetic questions.
- A possibly positive view-menu ceiling is only a restricted hindsight diagnostic. It does not establish a learnable online router or offset the multi-call inference cost.
- The only admissible next learned-Cell investment is a **different task family with independent evidence annotations and a genuine measurable action menu that nonlearning rules do not already saturate**, with a frozen Reader, full cost accounting, and no target leakage.

## Reproduction

With the exact repository checkout and the already verified 320/180/200 archive ZIPs:

```bash
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
python scripts/memory_cell/system2_cell_action_menu.py \
  /path/to/lexical-320.zip /path/to/tag-180.zip /path/to/placebo-200.zip \
  /new/output-dir
```

The original Cell-gate CI is extended to execute this read-only audit **after** its full regressions, Ruff and the six-scalar baseline, and to retain plan, sealed decisions, summary, every condition receipt and SHA256SUMS. A red inherited blocking gate is not ignored. This research PR remains draft and unmerged.

`production_accepted=false`, `general_ndu_fbsde_gain=false`, `independent_natural_task_evidence=false`, `actual_new_reader_calls=0`.
