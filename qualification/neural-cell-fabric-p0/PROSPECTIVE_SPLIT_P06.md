# P0.6 — preregistered Cell Split paired-outcome admission format

**DRAFT · SHADOW_ONLY · DENY_ALL · HOLD_NO_GO · NO_MODEL_SELECTION · NO_FINALUSE · NO_CNS_CUTOVER · NO_PHYSICAL_SPLIT · NO_MAIN_MERGE.** This is a source-only prospective *protocol checker*, not an experiment claiming new intelligence or improvement. Child of original P0.5; does not change the live Neuron, Stem, NDU, Worker, CAS, CNS, learning ledger, signing, or native effect owners.

## Why a new study, rather than another aggregate comparison

- P0.4 historical BANKING77: Split Head 20/32 and type-only no-SGD prior 20/32; zero-feature intervention yielded all 32/32 of the same binary *decisions*. Split against equal-touch shared was 12 paired wins, 8 losses (nominal McNemar p≈0.503); no independently established learned-semantic split gain.
- P0.5 historical AG News: trained gated Head 22/32 versus route-only prior 8/32, but the task, label space, encoder and costs differ from P0.4, held labels were in the original archive, and there is no matching equal-budget single Head versus Split comparison. This supports *task-specific* training value, not causal Cell fission.
- It is methodologically invalid to pool the two trials or promote either one by comparing their aggregate accuracies, descriptive p-values or number of logical Cells.

## Executable study interface

`prospective_split_panel.py` receives **separately delivered**, bounded strict-JSON packets:

1. **Prelabel**: exact `hepta.cell-fabric.prospective-prelabel.v1` envelope containing study ID, source families, FIT/CAL excluded roots, **five complete arms** (`no_change`, `equal_budget_single`, `split`, `type_prior`, `zero_feature`), per-arm claimed resource census (Encoder calls, physical Head calls, CPU microseconds, resident bytes), and source-root-bound predictions. This packet must **not** contain held labels. The reviewer requires its exact SHA-256 as a separate argument.
2. **Gold**: `hepta.cell-fabric.prospective-gold.v1` packet containing the same study/families and one complete case/Root/family/0–1 outcome mapping. Cross-arm identity, source-family separation, FIT/CAL exclusion, all-control completeness, duplicate keys, NaN/Inf, booleans, symlinks, oversized packets and forged SHA bindings fail closed.

For **each family independently**, it reports all five Head accuracy/Brier summaries; paired Split wins/losses against each control; Root-mean Brier gain; and a **descriptive** deterministic 512-resample Root bootstrap interval. It explicitly **does not** pool task-family p-values or treat many correlated Cell invocations as independent observations. Root counts are *declared* and not a verified source-independence receipt. Any output is a create-only private 0600 file, with actual input-byte SHA identities.

```bash
cd qualification/neural-cell-fabric-p0
python3 -m unittest -v test_prospective_split_panel
python3 -O -m unittest -q test_prospective_split_panel
python3 prospective_split_panel.py \
  --prelabel /private/label-free-original.json \
  --expected-prelabel-sha256 <sha-from-a-genuinely-independent-before-label-archive> \
  --gold /private/separately-delivered-gold.json \
  --output /new/private/p06-review.json
```

A user-supplied matching digest **does not establish when it was frozen**. This tool cannot authenticate external issuer identities or label custody, establish independent future-source data, prove actual resource invoices or equal-budget hardware costs, reexecute the model, evaluate real NDU long-horizon utility, detect unseen pretraining contamination, or verify old-task retention. Therefore `status=HOLD_NO_GO`, `authority=DENY_ALL`, all production/selection/Split flags false **even for a numerically perfect synthetic panel**.

## Mandatory next evidence to lift the *science* (not authority) gap

An independently held prospective study must pre-register the same frozen Encoder/task/Head bundle and actual resource budget **before** seeing source-family gold; materialize real prelabel model invocations and physical work counters; secure an independently timestamped prediction receipt, independently custodied human outcomes and original source/root lineage; compare same-input/same-budget Split, no-change, single Head, type prior, zero-feature and old-task retention; then evaluate after both windows close using an independent evaluator. This P0.6 format is a small precondition only; independent selectors, signed Artifact CAS → migration → CNS/Supervisor generation fence → Final-use remain entirely separate and blocked.

**Evidence classification:** the 13 new source-only tests are synthetic protocol checks (including malicious and altered packets); no fresh Encoder forwards, unseen gold, real CellSplit, independent prospective effect, real device benchmark or production CI acceptance is implied by their success.
