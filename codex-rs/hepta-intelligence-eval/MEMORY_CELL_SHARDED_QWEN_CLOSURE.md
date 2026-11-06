# MemoryCell 40+72 disjoint Qwen CPU shards (research only)

## Why a new pipeline is required

The exact historical strong-RAG run [38111452963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963) passed scoped format tests, installed the pinned CPU environment, replayed the frozen event indexes and staged the actual Qwen2.5-3B research model. The reader was cancelled near its 180-minute budget during calibration. The uploaded source-pinned artifact `11696974258` (outer ZIP SHA-256 `129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8`) has 4 valid original `raw-answers.jsonl` rows out of 40 calibration attempts, zero failed rows, **25/25** complete archive manifest hashes, and **no frozen selected-k**. Those four answers are not an independent model effect or completed baseline; the missing 36 and 72 are not imputed.

The original CPU model calls took approximately 923.308, 1457.513, 2045.598 and 2641.516 seconds, increasing with evidence length. This is incompatible with a sequential 40+72 reader job and motivates splitting work, not relaxing the reader model, changing task definitions, or converting earlier answers into new observations.

## New workflow and source contract

`.github/workflows/hepta-memory-strong-rag-sharded.yml` is opt-in on source-pinned branch pushes affecting this pipeline. Its exact-source stages are:

1. Model-free tests and source format check; `blocking-ci` and the PR-wide format gate remain independent and unchanged.
2. Restore the externally pinned original event ZIP (`11669174727`) and publish a **calibration-only** artifact, separate from the original held-out test labels. Import only the Qwen model identity files `stage.json`, `inventory.json`, `publisher.json` from the SHA-verified, historically staged Qwen artifact. Do not import its previously generated answers.
3. Run **16 disjoint calibration shards**, 8 fixed questions by 2 non-overlapping registered groups, totaling 40 actual Qwen answer calls. Each shard binds source commit, candidate digest, original bytes, reader identity, prompt, raw output, host receipt and artifact SHA pins; failed/partial tasks cannot be silently scored.
4. Collect exactly all 40 original calibration rows, open **calibration-only** labels after complete generation, recompute the registered objective and leave-one-out sensitivity, and freeze the top-k policy with its original source and model SHA.
5. Only then run **16 disjoint test shards**, 8 questions by 2 non-overlapping groups, covering the unchanged 9-arm census of 72 actual model calls. Test labels cannot be used for top-k selection.
6. Merge the 72 raw outputs without rewriting answers, re-execute constrained-program tasks, compute same-reader paired contrasts, one-hop vs traversal vs correction effects, actual inference token and time costs, and formal citation-chain coverage.
7. In an independent checkout/process, recompute the complete **32 shard-source receipt** and replay the full original-answer, citation-chain and score audit. Any omitted shard, modified original source, changed reader or missing reference fails closed.

### Canonical model metadata and cost integrity

`reader_reference.stage` records runtime download `seconds` inside `stage.json`; independent staging therefore yields unequal **file hashes even when weights and code are identical**. The original sharded collector requires stable model-stage SHA to prevent different weights being blended. `strong_rag_sharded_ci.py` resolves this without changing model weights: independently stage the full Qwen revision in every execution job, compare every newly generated inventory and publisher byte against original externally pinned model identities, then align only the immutable identity-stage file. The model's actual per-shard download duration is separately printed and archived as a staging receipt. The canonical `stage.json.seconds` was observed historically and **must not be counted as a new shard's staging cost**. The final production lifecycle cost is unmeasured, never zero.

All model shards retain the exact Qwen `Qwen/Qwen2.5-3B-Instruct` revision `82f42baa094a9600e39ccd80d34058aeeb3abbc1`, BF16 CPU eligibility checks, the unchanged reader prompt and decoder, and original read policies. Qwen remains research-only under its license. No model weights are included in output artifacts.

### Results and limitations

This workflow is an implementation and source-registration advance, **not completed model inference**. Calibration/test results remain unknown until every model shard finishes and both independent verifier gates pass. The eight pre-authored event queries are exposed development tasks; no 99% semantic entailment, independent future source family, parametric memory benefit, distributed recovery, production write authority or rollout qualification follows from pipeline success. Keep `production_accepted=false` and retain unrelated Stem commits and required repository CI.
