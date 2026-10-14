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

The 27 new confirmatory tests were validated locally on Python blobs matching GitHub; 20 additional earlier prototype tests are separate and not exact-parent CI. The separate real ZIP audit has 16 synthetic adversarial tests. Local checks are never a substitute for exact-HEAD CI or original source/model attestations.

## Public E1/E2 physical-source reproduction

Actual external research artifacts were downloaded from completed source PR #1775 runs [38541658096](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38541658096) and [38541658121](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38541658121). The new [public numeric ZIP audit](e1e2_public_receipt_audit.py) **reads only archived JSON**, never executes upstream code or imports model weights, and recomputes 128-case joint-input/source identity, four binary probability metrics, checkpoint payload SHA-256 and a separate-process Float64 Head replay.

Pinned artifact IDs: `11886761368` and `11886807698`. Exact ZIP hashes: `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d` and `7e244bb0994d7e086979e9f9743bb61474a7564fbec3476a20a4017700d4b469`. Download them only through an authenticated, read-only Actions artifacts API, then run:

```bash
python3 experiments/shared_stem_cell/e1e2_public_receipt_audit.py \
  --paired-zip /approved/paired.zip \
  --paired-sha256 e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d \
  --sealed-zip /approved/sealed.zip \
  --sealed-sha256 7e244bb0994d7e086979e9f9743bb61474a7564fbec3476a20a4017700d4b469 \
  --output /sealed/real-public-review.json
```

**Important:** The command above is a usage example; use the full 64-character hashes printed earlier in this document (and pinned in the workflow). The immutable machine-readable [completed local review](E1E2_PUBLIC_ACTUAL_RECEIPT_20261014.json) is authoritative for the precise values.

Observed new-file `val2` AG News accuracy/Brier (128 rows, binary world/sports): frozen Gemma .3828125/.25001948; trained Gemma .9375/.24881424; trained Gemma with previously explored 1024 logit multiplier .9375/.04932607; frozen Laya421 .96875/.02012669. Raw predictions agree exactly across paired and sealed runs, and canonical checkpoint digests match; 2,018 trainable Head parameters and 40 training steps are recorded. Discordance between Laya and trained Gemma is five cases in Laya's favor versus one in Gemma's favor (two-sided *unadjusted* exact McNemar p=.21875). This sample does not establish a statistically certain accuracy advantage for either model.

No chronological future1/future2/future3, no independent model-origin signer, no physical-forward count attestation, no public-data pretraining contamination exclusion, no matched training+serving+energy cost, no adequate Reader/independent NDU, and no production authorization. The prior temperature exploration and public same-family source selection are explicit; do not present this as a new temporal future holdout or a Stem winner.
