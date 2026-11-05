# Weight-space programming: current-source refresh

Checked at 2026-11-05 05:13 UTC (2026-11-05, America/New_York).

This is a literature/source review. It contains **no new Pocket4 observation, model execution, training run, weight edit, or Hepta efficacy result**. Earlier work was found in `/workspace/scratch/237419f85815/literature/` and `/workspace/scratch/ad8dc3f3c796/hepta-wsp-followup/`; those records must retain their original identities.

## Decision

The MIT work is real and materially relevant. It supports targeted gradient-free repair and neural policy construction in the reported settings. It does not establish an inexpensive general replacement for training, arbitrary neural-circuit understanding, or global NDU optimization. A useful Hepta subsystem should combine bounded inspection, analytic diagnostics, causal interventions, immutable edits, independent evaluation and rollback. Calling a closed-form supervised fit “no training” would be incorrect even when it uses no gradients.

## 1. MIT: source identity, exact intervention, and cost

The original publication is the November 2 research **blog post**, not a confirmed archival paper: [Takehi et al.](https://rikiyat.github.io/blog/weight-space-programming/). Its released repository HEAD remains `4d09ba6d6a7e891dd8063974dfe81b3d78e3494f`. The release identifies `gpt-6-astra`; its built-in CLI tools were disabled, while an external harness executed Python and target-model requests in the larger experiments. Earlier prompt-development trials are excluded from the release. [M1]

The Qwen experiment permits target generation and teacher-forced reads, including activations. A nominal forward pass is a **batched request**, up to 512 generation problems or 1,024 teacher-forced texts. Gradient/backward/optimizer training and iterative loss fitting are forbidden. The p50c run used 50 such requests, 158 editor turns, 80 Python runs, four conversations and 20.3 hours elapsed, including 4.7 hours of editor-service waiting. Failed requests do not consume the nominal pass budget. These quantities are not complete GPU, energy or dollar costs. [M2]

For each selected layer the logged final update is

\[
 W'_\ell=W_\ell-6u_\ell\bigl(m_\ell\odot u_\ell^\top W_\ell\bigr),
 \qquad\ell\in\{15,19\}.
\]

The layers' `mlp.down_proj.weight` tensors each have shape 1024 by 3584; the mask selects 64 columns. Directions come from four matched productive/repetitive original contexts. For a unit direction, selected components change from (a) to (-5a) before rounding. This is reversal and amplification, rather than merely an orthogonal-component deletion. The authors' layer-isolation, dose and random-direction controls support the proposed mechanism within their measured setup. [M3]

The manifest counts 130,188 actual changed BF16 entries, versus 131,072 addressed positions. Layer 15 changes 65,260 entries and layer 19 changes 64,928. The respective relative tensor changes are approximately 10.64% and 8.11%; a small fraction of the whole model does not imply a small local perturbation. [M4]

The authors' final confirmation reports 579 rescued practice answers and five regressions; 576 rescues had previously reached the token limit. Some whitespace degeneration, math errors and missing final answers remain. The benchmark scores and the practice confirmation are different evaluations. [M5]

Author-reported scores under the common thinking/sampling protocol are:

| Model | MATH-500 | GSM8K | IFEval | MATH answers at token limit |
|---|---:|---:|---:|---:|
| Original Qwen3.5-0.8B | 7.9% | 13.8% | 21.0% | 93.0% |
| 10-request edit | 12.3% | 25.7% | 49.0% | 87.2% |
| 25-request edit | 14.1% | 25.1% | 39.9% | 86.4% |
| 50-request edit | 48.1% | 67.1% | 62.3% | 33.1% |

These are read from the authors' experiment records, **not reproduced in this review**. Different budgets produced different edits, with one reported discovery run per budget; they are not a controlled learning curve of the same edit. [M2]

Qwen's official model card documents thinking loops and recommends task-specific sampling adjustment. This supports keeping strong zero-edit configurations in any comparison. [Q1] The authors' additional non-looping Gemma control establishes no substantial improvement in the tested searches. Failure of these searches is not a theorem that all future edits must fail. [M6]

## 2. Reproduction must have separate levels

1. **Exact artifact replay.** Use Qwen base revision `2fc06364715b967f1860aea9cf38778875588b17`, the pinned p50c `edit/manifest.json`, `edit/edit.npz`, `code/apply_edit.py` and adjacent `code/st_numpy.py`. Run `python apply_edit.py BASE.safetensors EDIT_DIRECTORY OUTPUT.safetensors`. The script checks dtype, shape, base-tensor SHA256 and rebuilt-tensor SHA256. Output must go to a separate artifact. [M7]
2. **Capability replay.** Freeze the tokenizer, template, thinking flag, dtype, target engine, prompt, grading and samples. MIT uses temperature 0.6, top-p 0.95, top-k 20, presence penalty 1.5 and max 32,768 new tokens; MATH-500 has four samples/problem, GSM8K two, and IFEval two with strict prompt-level checking after the thinking block. Preserve generated answers and all error/timeout records. [M2]
3. **Independent discovery.** Hide the known layers, direction, mask, scale and published solution from fresh editors. Reimplement the permitted request interface, enforce request and complete resource budgets, and repeat independent discovery sessions. The original full agent/forward server and intermediate work folders were not released; byte-identical original-harness replication is unavailable from the public package. [M2]
4. **Hepta transfer.** Requires its actual checkpoint, architecture, frozen state/action semantics and a fresh selection/test split. Previous success in stages 1–3 does not establish this stage.

## 3. Newly checked follow-ups

### Steer2Edit v3 is newer than the preceding Hepta literature note

[Steer2Edit v3](https://arxiv.org/abs/2602.09870v3) was submitted November 4, 03:41:39 UTC and is marked accepted to NeurIPS 2026. The earlier local note cited v2. The rank-one/soft-threshold formulation remains; v3 adds comparisons and scale/architecture tests. Local orthogonal-output preservation is not full downstream capability preservation. Its 70B table's maximum-safety row has utility 35.7 versus the base's 51.8, and its vision-language extension evaluates text-only tasks. Those claims must keep their scope. [S1]

The [official code](https://github.com/Trustworthy-ML-Lab/Steer2Edit/tree/86382c2f44fdfda2bafe80faf09634e6d729562c) generates probe responses, extracts activation directions, constructs multiple candidate edits and evaluates them. The paper describes a 5×5×5 coarse hyperparameter grid followed by refinement. “Single-step” describes the conditional algebraic update, not the full acquisition/selection pipeline. [S1], [S2]

### New November 4 practice-set comparison

[aiXiv v1.1](https://aixiv.science/abs/aixiv.261103.000004) reports, on 64 practice problems with four samples each: original 10.2%, published MIT edit 64.8%, difference-of-means script 60.9%, best tested decoding intervention 47.7%. The script was supplied MIT's layers, scale and column budget. Script-minus-MIT has reported 95% interval −9.6 to +1.8 percentage points, which does not establish equivalence. It does not evaluate MATH-500/GSM8K-test; its new raw records, code and full hashes remain unreleased. Four alternative-editor runs ended before their nominal request budget and report selected development gains on differing sets. Treat this as a preliminary external report, not independent complete reproduction or a cost-superiority result. [A1]

### Other primary records remain bounded

The [Turing repository](https://github.com/alan-turing-institute/weights_editing) remains at `9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca`. It replicates small-network experiments and includes swapped-action/board controls. Its scope excludes Qwen experiment 8. Its direct Python-policy comparator is an important reminder to separate discovering a policy from compiling that policy into neural weights. [T1]

The [clinical-network preprint](https://arxiv.org/html/2611.05341v1) reports localized repairs but also healthy-network false alarms, missed triggers and failures after low-precision conversion. Its fine-tuning comparator takes seconds per small-network run, whereas weight audits take minutes. These are external synthetic experiments, not medical advice or deployment evidence. They demonstrate why sparsity alone cannot establish speed, safety or complete correctness. [C1]

`cert-machine` HEAD changed to `145f76c131d64966510f901f816074246642abd3`, but `certs/wsp-baseline.json` still has blob `e3ce4652c2f3f152e582aefdd2db10c851264dac`, identical to the preceding review. The file's contents were empty in the current large-file fetch, so this refresh establishes **identity continuity**, not a new read or fresh execution of its old numbers. Its strong no-edit design remains relevant; its grader differs from MIT's and its full edit-by-configuration factorial is incomplete. [B1]

## 4. Hepta experiment recommendations (new design inferences)

These are proposed controls, not observed Hepta improvements.

- Give each hypothesis an observable consequence: state aliasing, incorrect reset ownership, Call/Put parity error, belief miscalibration, terminal bootstrapping, or continuation advantage with incorrect future cost. Locate failures using architecture and source semantics before attributing them to weights.
- Protect identities by construction where feasible: derive Put from Call, fix terminal payouts and legal actions, keep Reset/event semantics explicit, and enforce positive/time-domain parameters. A hard-coded semantic fix belongs in a code/configuration arm, with its gains separated from weight editing.
- Compare a strong no-edit/configuration arm; a same-information direct analytic diagnostic/solver; an LLM-guided edit; a sham/random edit with matched changed positions and norms; head-only gradient training; and the strongest affordable full-training baseline. Closed-form supervised ridge fitting is still learning and should be named accordingly.
- Preserve the established A/B/C/D factorial of ordinary/analytic core and light/value control. Run the editing comparison within the same base checkpoints, law, observations, action semantics and execution budget. Report D−B and the interaction, not only lower prediction loss.
- Freeze discovery, selection and held-out tasks. Multiple target episodes for one edit are not multiple independent edits. Repeat independent editor sessions and model seeds; report failures, no-update decisions and all search costs.
- Use functional controls for raw-weight interpretation: hidden-unit permutations, and positive ReLU rescaling only where algebraically valid. Do not assume arbitrary rotations preserve nonlinear networks. Require causal patching or matched intervention before accepting a circuit explanation.
- Account for target forward tokens, activations, transfer, CPU/GPU, editor inference, candidate search, failed requests, tests, serialization and rollback. Compare complete cost per accepted quality improvement, and p50/p95 latency, memory and measured energy where available. Missing historical cost stays unknown.
- At deployment dtype, check actual rounded deltas, NaN/Inf, extreme tails, reset boundaries, OOD and retained tasks. An exact certificate for a convex head or finite modeled Bellman graph does not certify the unknown real environment or global neural-network optimum.

## Primary references

- [M1] https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/README.md
- [M2] https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/README.md
- [M3] https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/runs/p50c/work_notes/final_report.md
- [M4] https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/runs/p50c/edit/manifest.json
- [M5] https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/runs/p50c/final_answer.md
- [M6] https://rikiyat.github.io/blog/weight-space-programming/
- [M7] https://github.com/RikiyaT/lm_understand-logs/blob/4d09ba6d6a7e891dd8063974dfe81b3d78e3494f/exp8_math/code/apply_edit.py
- [Q1] https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/main/README.md
- [S1] https://arxiv.org/html/2602.09870v3
- [S2] https://github.com/Trustworthy-ML-Lab/Steer2Edit/blob/86382c2f44fdfda2bafe80faf09634e6d729562c/README.md
- [A1] https://aixiv.science/pdf/aixiv.261103.000004v1.1.pdf
- [T1] https://github.com/alan-turing-institute/weights_editing/tree/9b4a7f1b23a1cc2e1290e4c73ebcb77e87a285ca
- [C1] https://arxiv.org/html/2611.05341v1
- [B1] https://github.com/carlostoledo1891/cert-machine/blob/145f76c131d64966510f901f816074246642abd3/certs/wsp-baseline.json

Useful additional primary method sources, read during this refresh:

- CrispEdit, ICML 2026: https://proceedings.mlr.press/v306/ikram26a.html — capability-preserving constrained second-order editing; not a gradient-free replacement for all training.
- Wait, Wait, Wait… Why Do Reasoning Models Loop?, ICML 2026: https://proceedings.mlr.press/v306/pipis26a.html — separates correlated learning errors from decoding exploration; reducing loops alone does not identify general reasoning improvement.
