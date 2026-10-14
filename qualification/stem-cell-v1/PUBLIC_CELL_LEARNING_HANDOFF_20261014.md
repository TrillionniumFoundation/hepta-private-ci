# Shared pretrained Encoder: public-data Cell learning canary

Parent: `805ffeae04db9c0d7d3386cb2a2644dd29f39b07` (PR #1804).
Published code: `4b093b9c3399e463ff02d8d52f6b6b72d7bcc8b1`.
Branch: `research/shared-stem-public-cell-learning-20261014` (PR #1825).
No main merge, production selection, native installation or matrix NDU activation.

## Next executable experiment

The preceding public Encoder probe performed three/six feature forwards. This
increment connects the existing LocalHFEncoder, CellBank, train_bank, WorkLedger
and safe prediction/weight seals to a small, fixed natural-language learning task.
It is deliberately a public-data integration canary, not the original nine-arm
421M protocol and not an assertion of independent statistical efficacy.

The installed-HF workflow first verifies the real stock Encoder-to-two-bank
connection. The existing public job then reuses its pinned ModernBERT snapshot
and acquires only the original BANKING77 train/test CSVs and license at commit
`57ec275d8078af65b7731c2a98be812d844a6d6b`. Exact Git blobs are checked before
parsing; actual SHA256 values and the original license are retained. No dataset
Python script executes, no credentials are used for acquisition, and source
files/partial failures cannot be overwritten by retrying the same directory.

The model source lock must identify the fixed public checkpoint revision
`8949b909ec900327062f0ebf497f51aef5e6f0c8`; its material/snapshot link is checked.
One model is resident per learning process. The previous probe process exits
before this step; this is not two simultaneously resident model copies. Loading
and reverification costs are not silently included in the narrower ATen graph
measurement. No pretrained base weights are uploaded as learning artifacts.

## Fixed data and schedule, not outcome-driven selection

Four intents are fixed in source: card_arrival, cash_withdrawal_not_recognised,
exchange_rate and lost_or_stolen_phone. Each uses 16 fitting examples from the
original train split and 8 heldout examples from the original test split: 64/32
in total. Selection is by a fixed salted content hash before seeing any model
score. Normalized duplicate text is deduplicated deterministically; all normalized
train/test overlap is excluded before test selection. Conflicting labels or
insufficient remaining examples reject, rather than silently shrink denominators.
This is not semantic deduplication, a source-independence guarantee, or a check
against the model having seen public data during pretraining.

Heldout inputs contain only IDs and text. The actual training API has no heldout
target argument; the Encoder receives the same question/options and utterance,
not row labels. Both arms finish or fail before a single common target join.
The outer diagnostic process prepares labels earlier but passes none to the
training function: this is software separation, NOT OS isolation or independent
observer authentication. There is no validation tuning, retry-until-success,
accuracy threshold or model selection based on this 32-example panel.

Default learning is 64 AdamW steps, batch size 16, seed 7347, width_units 16.
Both banks have 16 physical Heads and exactly the same initialization and actual
parameter count; only dense all-16 versus learned top-2 activation differs. For
768D features and four outputs the existing formula gives 395,776 trainable
Head-plus-gate parameters per bank, NOT 32M parameters just because the allocation
ceiling is 32M. This is a geometry calculation, not an observed real-model result.
No artificial 421M arm ID is attached to the 149M-class Encoder.

## Real execution and costs

The frozen Encoder computes all 64 fitting and 32 heldout vectors once. This
shared work is reported once at experiment level, separately from each bank's
training and before/after heldout forward passes. Each bank is optimized and
serialized sequentially. Its actual weights, initialization/trained digests,
optimizer tensor bytes, selected Head-row counts and work observations survive
in the terminal records. An actual parameter update is required for a successful
training terminal; high classification accuracy is NOT required to pass CI.

Equal steps and seeds do not imply matched FLOPs. Sparse routing actually executes
selected subsets, but shared encoding can dominate overall cost. Reported bank
inference includes the initial diagnostic and the final diagnostic. It is NOT
end-to-end service latency, p95/p99, target GPU throughput or per-request memory.
ATen V3 strict coverage and pre-dispatch caps remain in force. Unknown/failed
work is not zero. Model loading, Python preprocessing/scoring, publication,
process-attributed energy and complete live-memory accounting remain outside the
narrow formula-work scope. No latency/energy advantage is inferred from routing.

Each arm has an exclusive success seal or FAILED record. Failed attempts keep
all heldout opportunities and observed work; their delivered-answer accuracy is
zero under the fail-closed canary, not an estimate of the rejected model's ability.
Missing records block scoring. Saved Head files and predictions are content bound.
The post-training Encoder tensor verification must succeed before a campaign
terminal is published. Final scoring reports accuracy, NLL, multiclass Brier and
per-class accuracy before/after, but retains efficacy_established=False and
full_system_cost_measured=False. No legacy final-panel statistical gate is bypassed:
these canary artifacts explicitly are not accepted nine-arm qualification exports.

## Verified in this session

Fifteen new tests executed actual small PyTorch bank training/serialization with
an explicitly synthetic feature provider, plus material-download test doubles.
They check fixed selection, heldout-label rejection, actual matched parameters,
initialization and sparse execution, post-training weight changes, saved-weight
round trips, source/weight tampering, failure denominators and no training during
scoring. They are not substituted for public-data/pretrained execution.

Two complete local shard runs each covered 436 distinct planned/executed tests:
421 retained plus 15 new, counts 56/56/54/55/54/54/54/53. All sixteen process exit
codes are zero; no errors/failures/skips. Five uploaded code/workflow blob IDs
match the tested bytes. Compileall, diff whitespace and YAML parsing passed.
The initial whole-suite baseline command timed out, leaving an incomplete report;
its log is retained and NOT counted as a successful baseline run.

The predecessor's completed hosted artifact was independently downloaded and
verified in this session: run 38518475547 / job 115702526181, actual checkout
`8b6961ea1012428dd8e83bb00110b0b16cd8c9ff`, 421 planned/executed tests, complete,
zero errors/failures/skips. Its forty test-source hashes match the local retained
files. That belongs to parent code ac445d2, not to this new learning code.

This session has no Transformers; the separate five-case installed-HF check
fails at import, executes zero cases and is not counted in 436. Local attempts
to download public materials did not succeed. The newly triggered hosted run
38522305228 was last observed queued. No actual BANKING77/pretrained learning
score, matched-cost superiority, native/GPU/Rust/full-repository or all-CI-green
claim is made in this receipt. Later hosted observations must be bound to their
own actual checkout and artifact IDs, not inferred from local tests.

## Attribution and reproducibility

Original data is copyright PolyAI Limited under Creative Commons Attribution 4.0:
https://creativecommons.org/licenses/by/4.0/
Source: https://github.com/PolyAI-LDN/task-specific-datasets
Cite: Casanueva, Temcinas, Gerz, Henderson and Vulic (2020), Efficient Intent
Detection with Dual Sentence Encoders, 2nd Workshop on NLP for Conversational AI,
ACL 2020. The CSVs remain unmodified; normalized deduplication, deterministic
four-class subsampling and input/target projection are the transformations here.
The workflow retains the exact original license and small learned Head artifacts,
not the raw public CSVs or the base model weights.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --output /new/source-tests.json
python qualification/stem-cell-v1/public_cell_learning.py \
  --public-probe /completed/pinned-public-encoder-probe \
  --acquire-banking77 --output /new/public-cell-learning
```

The second command deliberately downloads the three fixed public dataset files;
it requires the already completed public Encoder acquisition and reviewed runtime
dependencies. Preserve the raw terminal and score files whether accuracy improves
or not. Repeated attempts and future extensions need their own predeclared tests;
this subset cannot establish multigeneration retention, reasoning, multimodal
generation, 1024/4096-Cell deployment or 10T/100T capability equivalence.
