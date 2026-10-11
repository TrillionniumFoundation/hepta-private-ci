# Four-gate remote import and next implementation plan

Date: 2026-10-11. Scope: research source preservation, evidence review and prospective implementation planning. No model selection, main merge or production activation.

## 1. Remote delivery now completed

The original nine-file patch is preserved byte-for-byte in commit `88d248277e853b96613f6b442386c25921ad2372`, tree `9b07952db9ffe0194ac3d047df2feadb4414ac3b`, on `experiment/neuron-four-gate-offline-import-20261011`. Its parent is the inspected `6f7e3e1040fd26ddef6600d6440572c58de1de6e`; the original parent tree is `63c2fecd29c8cfd011067a66568a6d235647f615`.

All nine GitHub-created blob identities matched the local originals. The branch ref was read back and matched the import commit. This supersedes the historical delivery-status paragraphs in the original source guide and `RESULTS.md`; those paragraphs are retained as historical records rather than silently rewritten. The historical experiment results are not new final-head model executions.

The requested acceptance branch name already existed. PR #1526 uses `experiment/neuron-four-gate-acceptance-20261011`, observed at `6c4b6d562f2d818bfdffc2b3e26bcf65a0d0b5bf`. Its implementation is different and shares the exact path `qualification/neuron-stem/four_gate_review.py` with the imported patch. Neither that branch nor its files were overwritten. The live Jina parent branch was separately observed at `efbb499cccaea72d7a06e30a9ff6ab3f6f28ae56`; the import does not pretend to include its later changes.

Recommended continuation: use PR #1526's existing acceptance reviewer and owner-facing capture contracts as the convergence target, port the useful controlled probes through explicit versioned adapters, and retain this import as the historical experiment snapshot. Do not blindly cherry-pick the whole import over the other reviewer. No convergence is claimed completed by this document.

## 2. What was verified during this import

The delivered archive's 188 manifest entries were rehashed and its inventory matched. The unchanged source was retested locally: 62 protocol/adversarial tests and 13 real CPU tensor tests passed without skips. The local parent checkout and native Rust integration were not present. Local logs and the full raw archive remain in the conversation delivery; `IMPORT_MANIFEST.json` records their hashes, not a claim that their bytes were all uploaded to GitHub.

The separate existing PR #1526 had a completed successful dedicated run, `38119429179`, on its own source `6c4b6d56`: `offline (head)`, `offline (merge)` and `actual-cpu-mechanisms` all completed successfully. Its architecture and Stem-specific runs also reported success. Its whole-repository blocking CI was still queued at observation. None of these receipts qualifies import commit `88d24827` or a later planning commit. No new CI pass is claimed for this preservation branch.

## 3. Two additional findings that change the next experiments

### Constant-depth NDU control needs a stronger baseline

A fresh census of `evidence/final-source-learning-full/ndu-observations.jsonl` found 240 records per arm. Fixed budget always used 16 rounds; confidence always used one; deterministic NDU, recursive-risk NDU and generic nested-risk each used exactly 12 rounds on every case. Thus the previous mean depth of 12 did not establish input-dependent allocation on this sample.

The next experiment must include fixed 12 rounds and the best fixed depth selected on a separate validation set, not merely compare against fixed 16. Choosing 12 now is exploratory diagnosis of already observed data; a confirmatory comparison requires a newly frozen plan and untouched evaluation data. Preserve the old result, including its extra calibration cost and non-amortized lifecycle total.

### OOD acceptance is not automatically OOD error

In `cell_probe`, the generated OOD input is `3*x + 2` and the same linear label rule is retained. The current OOD loop discards the generated label and counts confidence-threshold acceptance. Its approximately 92%-95% acceptance therefore measures poor separation of this shifted-input class under that detector, not an observed 92%-95% incorrect-answer rate.

Do not relabel that historical number. Add actual OOD labels, correctness and abstention outcomes in a new protocol. Distinguish benign covariate shift, difficult in-domain examples, unknown task/intent, changed label mechanism and missing evidence. Rejecting every shifted but correctly answerable input is not the learning objective. Report accepted-answer error and coverage together, with thresholds selected only on historical calibration and bound to the relevant model/Head version.

## 4. Work packages and exit criteria

### P0 — Converge source and strengthen the common measurement contract

Start from exact pinned heads of #1526, this import and the later parent. Inspect path-level differences before any merge. Keep one authoritative review entrypoint and one versioned evidence bundle; preserve original byte hashes and provenance. A compatibility adapter may map explicit equivalent fields, but cannot invent an observer, an original no-change result, a native forward event or a future timestamp.

Preserve #1526's seven lifecycle phases: load, warmup, inference, training, search, evaluation and migration. The imported reviewer logs several phases but its NDU comparison score subtracts inference wall cost; that is not an adequate replacement for full-lifecycle evaluation. Keep the existing observed-evidence floor of at least 200 source clusters, together with a prospective power/precision analysis. The import's 30-component research diagnostic must not weaken that floor. Root clustering is necessary, not proof of independence.

Retain all 36 scale/active/repeat settings. Version any extension adding the import's three task-similarity strata and three repetitions rather than silently changing denominators. Preserve incomplete and failed workloads. Keep missing, invalid, not-passed and diagnostic-pass distinct. A complete census or zero CLI error is not a scientific success.

Deliverable: reviewed source-difference map, explicit schema adapters, merged regression corpus and exact-head plus prospective-merge test receipts. Exit only after inherited and added tests both execute without skipped numerical suites. No parent pin update merely to suppress drift. Split changes into reviewable commits, with no new production owner.

### P1 — Run one real pretrained Stem end to end before expanding the model matrix

Use one approved fixed-revision candidate first; mmBERT-small is the previously proposed starting candidate, not an established winner. Retain the actual current no-change model and genuine joint state/question/options baseline. Freeze actual weights, tokenizer, preprocessing, task adapter, precision, runtime and device identities; hash the local weight bytes and record the real load. Review model/code license and any remote-code execution before use.

Reuse #1526's loaded-Encoder capture interface for a research run, then bind the same request lineage through the existing native inference owner. A fixture driver cannot substitute for the Transformer forward. Each request must resolve to an actual forward event and batch slot or an admitted reuse dependency; bind principal, purpose, generation, authority epoch and the complete input. Cross-scope identical bytes do not grant reuse permission.

Compare original no-change, one shared-weight joint-batch model and reused state features plus question-conditioned Heads. Architecture quality is measured, not assumed equivalent. Record cold and warm loads, 0/50/90% repetition, all active Cell coverage, queueing and all terminal outcomes. Capture full request p99, successful throughput, continuous or independently measured peak RSS, actual CPU/GPU work and the complete lifecycle ledger. Missing energy or GPU measurements remain null where required, never zero by convenience.

Implement scoped immutable cache entries and grouped Head dispatch in the existing worker, rather than one process/optimizer per Cell. Measure cache-key, gather/scatter and Head overhead separately; permit an admitted direct-batch path when reuse is not worthwhile. The zero-repeat case must not disappear.

Exit: a real-weight, real-input quality/resource Pareto comparison within preregistered target-host budgets. Admit shared features only where quality is noninferior within the declared margin and resources improve. If tiny or low-reuse workloads favor joint batching, retain that path. Broaden to Jina or LFM candidates only after this vertical slice works; no floating revisions or unmeasured model ranking.

### P2 — Demonstrate genuine Cell learning and useful uncertainty handling

Preserve three matched arms: authentic no-change, same-initialization frozen Head, and trained Head. Freeze Stem and control weights. Use the existing prequential journal and Head update lineage; seal all predictions before the outcome can enter the optimizer. Record actual effective parameters, optimizer state, update cost and the option of no update for data-poor Cells.

Extend the protocol with OOD correctness, selective risk versus coverage, harmful-unknown false acceptance, in-domain false rejection, calibration and old-task retention. Compare confidence-only, a low-cost feature-support detector and a small learned rejector under equal approved data and budget. Calibrate before the future interval; a newly trained Head needs a declared compatible calibration policy rather than retrospective threshold adjustment.

Use authorized real tasks with source-family grouping and actual chronological windows. Keep failed, delayed and censored outcomes explicit. Preserve #1526's support/cluster, multiplicity, OOD and retention requirements. The future observer and training producer must be independently controlled; distinct string IDs are not authentication.

Exit: trained Heads beat both controls on the preregistered predictive estimands, retain old tasks, and meet the fixed selective-risk/coverage and unknown-input limits. An accuracy increase cannot compensate for unsafe accepted errors. Benign-shift acceptance is reported separately rather than automatically labeled failure.

### P3 — Test reasoning against the best cheap alternatives

Keep the current graph test as a mechanism fixture, not the main capability benchmark. Add fixed 12, validation-selected fixed depth, a shallow/nonrecurrent learned control with equal information, and direct BFS or another exact algorithm when the input already exposes a graph. An exact algorithm should win where a learned solver adds no value. Match the task definition and abstention/missing-evidence rule across arms.

Prepare mixed task difficulties, graph sizes and held-out generators/structures. Retain the five novelty strata, including temporal reversal, missing evidence, misleading hints and interventions. Prevent hint, size, generator and source artifacts from revealing labels. Add a bounded real Hepta task slice with independently verifiable consequences rather than simply renaming generated graph inputs.

Use the same Stem, training data and allowed observations; record actual sequential causal depth, policy choice, stop reason and the distribution of selected depths by task. Match per-episode and whole-lifecycle measured axes within the existing acceptance tolerance and absolute caps; equal optimizer steps or equal parameter names are not equal resources. Where exact matching is infeasible, report a measured Pareto curve rather than claiming superiority.

Exit: a repeated-computation benefit on untouched tasks survives the best validation-selected fixed-depth and equal-cost controls, in addition to the single-step comparison. Variable depth alone is not success; lower depth alone is not reasoning. Keep deterministic methods for deterministic subproblems.

### P4 — Establish incremental NDU value, including preparation and refresh

Give fixed-depth selection, simple cost-aware early exit, a small stopping router, deterministic NDU and generic dynamic-programming/nested-risk controls the same admissible information and calibration budget. Retain the algebraically equivalent generic recursion; do not claim mathematical exclusivity when it produces the same values. Separate common validation overhead from solver-specific runtime.

Charge every physical load, warmup, inference, training, search, evaluation, migration and cache-refresh job once. Amortize preparation only over actually observed uses of that valid model/critic/objective/scope generation. Estimate a planning break-even volume from measured preparation cost and per-query saving, but never use hypothetical future volume to pass the current gate. A generation change or incompatible critic invalidates the old cache economics.

Freeze the external goal and outcome semantics. Use cross-fitted/frozen critics and independent later outcomes. For coupled Cells, retain actual joint or conditional behavior support and group-level interference; repeated correlated activations do not increase independent sample size. Optimize both action quality and the value of acquiring evidence or further computation without changing the success criterion.

Exit: deterministic NDU improves the registered external quality/cost tradeoff relative to the best cheap controller after lifecycle costs, with retention by task stratum. Add a stochastic/dynamic-preference candidate only in tasks where uncertainty and risk genuinely affect decisions, then require incremental benefit over deterministic and equivalent generic controls. A negative incremental result keeps the simpler candidate selected; it does not halt the broader learning program.

A general FBSDE remains a distinct implementation package, not a label for this finite tree. It needs a declared filtration/driver, covariance/support checks, valid recursion/solver diagnostics and a justified parameter-gradient method. Z is not a parameter gradient. Neither a lower residual nor a higher fitted internal utility demonstrates task improvement.

### P5 — Native owner, recovery and prospective acceptance

Run the chosen candidate through the existing inference, Neuron checkpoint, artifact, evaluation and selection owners. Verify current final-use grants, true selected CAS, revocation/generation fences, crash/reopen, WAL/checkpoint replay, cancellation and rollback. Recovery must consume committed historical decisions rather than recompute them with a newer model or re-execute historical effects.

Collect actual future calendar windows and authenticated independent result observations under the preregistered evaluation design. No synthetic timestamps, repeated CI or replayed trajectories satisfy this condition. Only after the separate quality, resource, safety, lifecycle and recovery gates pass should an independently authorized canary and rollback review be considered. This plan grants none of those authorities.

## 5. Immediate next delivery

The next bounded implementation should deliver P0 source convergence and a single P1 real-model vertical slice, while implementing the cheap fixed-12/control and OOD-correctness measurement repairs needed by P2-P4. Its report should contain actual weights/load identity, matched three-arm request traces, complete resource costs, accepted-answer correctness, chosen-depth distributions and strongest-control comparisons. Do not spend the next iteration only adding another evaluator wrapper or running larger synthetic matrices.

All thresholds and confirmatory hypotheses must be fixed before new holdout outcomes are observed. The old generated results remain historical/exploratory. This document is a prospective work plan, not evidence that these packages have already been implemented or passed.
