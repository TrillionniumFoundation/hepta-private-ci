# E1–E5 independent paired confirmatory reviewer (shadow-only)

**Source code:** [e1e5_confirmatory_review.py](e1e5_confirmatory_review.py)

This follows the nonauthorizing structural audit in [E1E5_CAUSAL_FRONTIER.md](E1E5_CAUSAL_FRONTIER.md). It consumes independently staged *claims*, **not** model weights, outputs from a trusted remote Reader, or independently authenticated NDU receipts. It does not train, fetch, select, deploy, mutate Neuron V1, change a model, or grant FinalUse. Every output is DENY_ALL, `all_acceptance_gates_passed=false`.

## Reproduce on previously frozen files

```bash
python3 -m unittest discover -s experiments/shared_stem_cell -p 'test_e1e5_*.py' -v
python3 experiments/shared_stem_cell/e1e5_causal_gate.py \
  --observations /approved/observation.json \
  --output /sealed/structural.json
python3 experiments/shared_stem_cell/e1e5_confirmatory_review.py \
  --observations /approved/observation.json \
  --outcomes /independent/labels.json \
  --reader-trials /independent/reader-four-condition.json \
  --output /sealed/paired-review.json
```

The CLI creates the review file exclusively; it never overwrites a previous report. Inputs are each capped at 32 MiB, reject duplicate JSON keys and nonfinite numbers, and are hashed in the result. These hashes are *integrity identifiers*, not independent signatures.

- Observation schema: `hepta.stem-e1e5-causal-observation.v1`; exact input/source/dataset/plan/worker-model digests, scoped disjoint cases, complete named arms and per-case prelabel-sealed **claims**. Each arm must supply all lifecycle fields: load, encoding, Bridge fitting, Head training, caching, migration, recomputation, serving, evaluation, checkpoint, RSS, CPU, GPU, energy, throughput, p95 and p99.
- Outcome schema: `hepta.stem-e1e5-independent-outcomes.v1`; match `dataset_sha256`, `plan_sha256`, a distinct `producer_id` and one `rows` entry for each case. Each row binds `case_id`, `source_group`, `input_sha256`, `split`, `observed_at`, binary `label`, and `outcome_sha256`. No row replacement, missing labels, same-producer claim or per-case identity drift.
- Reader schema: `hepta.stem-e1e5-reader-four-condition.v1`; `trials` contain one record per `(task_id,condition)` with conditions `none`, `retrieved`, `sufficient`, `premise_removed`. Hold task input, Reader model digest, prompt template digest, seed, token budget and source group fixed across conditions. Task input and source group must match a study case. Sufficient evidence needs a declared reviewer ID and reviewed-evidence digest; removed-premise requires a deleted-critical-premise digest. These fields **do not authenticate** an actual review or prompt content.

### Stage-specific rules

**E1:** Exactly one candidate per study: `granite_97m_r2` = 384D / `cls_l2`; `mmbert_small` = 384D / `mean_l2` (research readout); `embeddinggemma_2_text` = 256D / `matryoshka_256_l2`. Require immutable 40-character upstream revision, tokenizer SHA-256 and the **same Encoder** for learned/frozen Head. The independent production no-change arm can be a different model. Do not use equal original strings as a substitute for real, per-model tokenizer/FLOP measurements.

**E2:** Same frozen Encoder across non-no-change arms. Full trainable residual Head parameters must be within the *complete* 2,048 / 8,192 / 16,384 ceiling, actual optimizer steps declared positive and baseline-preserving initial output declared; none of these declarations verifies optimizer gradient traces or weights.

**E3:** Compare `text_only`, `ocr_only`, `unaligned`, `learned_bridge` and `native_multimodal`; task labels and outcomes must come from actual unseen visual relationship tasks. A geometry or mean-fusion toy result is not enough.

**E4:** Every reviewed video temporal counterfactual comprises **exactly two source-group-matched clips in one split**, identical `frame_content_multiset_sha256`, distinct `frame_order_sha256` and opposite independent labels. Such digest claims alone are *not* visual inspection or evidence of actual frame reversal. Genuine acoustic task scoring remains separate.

**E5:** One `logical_cells` cohort per report (64, 256, 1,024, 4,096), with a declared active count and a `worker_trace` carrying a claimed target host, Stem digest and one request per activity. Reject fake cache hits without a preceding miss, forward ID reuse for changed inputs/scope/generation, missing per-request FinalUse checks and incomplete active-Cell IDs. Native batch execution and physical receipt signatures are **not** verified here.

### Paired statistics and interpretation

For each required candidate–control pair, compute source-group mean classification-accuracy differences separately on **future1, future2 and future3**. Fewer than **50 independent source groups in a window** yields `lcb_accuracy_gain=null` rather than a made-up interval. Otherwise calculate a deterministic 2,000-draw group bootstrap lower bound with a family-size multiplicity correction. These are descriptive intervals conditional on the supplied data, not unbiased causal effects, noninferiority certification or NDU utility.

Include per-arm reported lifecycle time, RSS, p99 and **unadjusted** OOD confidence ≥0.95 fraction as diagnostics; the latter is *not* a trained calibration threshold or an OOD acceptance proof. Reader success on all supplied sufficient-evidence tasks is reported separately from *coverage of all three future windows*; neither proves independent grounded answer correctness.

### Non-waivable missing evidence

Until there are independently authenticated model snapshots and physical forwards, held-out Reader semantic reviews, signed external outcomes, prelabel journal authority, external future-window NDU, target-host hardware counters, actual Rust microbatches/WAL/fault recovery, current revocation and exact-head **blocking-ci**, no model selection or production promotion is permitted.

The 47 local synthetic/model-free tests reported during authoring prove only the described mechanism. They are not the exact-head CI status, not external dataset/model outcomes and do not establish any advantage over Laya 421M or independent frozen controls.
