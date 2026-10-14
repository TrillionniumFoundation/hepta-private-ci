# Exact-view shared Stem fanout, 2026-10-14

Parent: `2082d83e43f65dfa1f652879405235455a9ccf5e` (#1892).
Tested code: `8b1a923fcfa029b7b683e92c4c133ebc53d289c8` (#1903).
Branch: `research/shared-stem-exact-view-fanout-20261014`.
Research/qualification only. No main merge, deployment, model selection or matrix NDU activation.

## Implementation and accepted reuse boundary

`shared_fanout.py` actually feeds N distinct CellBanks using one physically executed frozen Encoder call. The control executes the same Encoder N times, not a cost multiplier. Both cases charge true Head/router operations, use separate strict dispatch ledgers, and compare each consumer's logits and token counts. No persistent feature cache exists. A complete typed request includes principal scope, state, question, ordered options, sample/time identity; any difference forbids reuse. The bounded path checks CPU FP32 backing storage, logical Cell counts (max 4096), evaluator mode, unique consumers, unchanged trained Head state, formula budgets, unknown work and numeric parity. Scope hashes are consistency checks, not authenticated principal ownership.

`public_fanout_probe.py` can load one pinned complete ModernBERT checkpoint from local safetensors, verify physical materialization, and compare one against seven real Encoder forwards serving seven 16-Cell banks. The MLM head is retained in memory but cannot run for these features. **All seven pretrained-canary Head banks are untrained**, so the canary does not test independent task learning or generation.

## Local evidence actually executed

13 new fanout tests exercised actual PyTorch trained small Head banks and a deterministic synthetic Encoder. Seven 16-Cell banks, 112 logical Cells: shared case 1 physical Encoder call, 9,557 formula operations; repeated case 7 physical Encoder calls, 16,373 formula operations, maximum task-logit difference zero. This is **41.63% less scalar-equivalent formula work** on the tiny synthetic reference. Instrumented wall times were approximately 16.736 ms (shared) and 14.797 ms (repeated): **no latency speedup established**. It is one input, not seven evaluated independent task families.

Source-only full suite: 494 predecessor + 13 new = **507 distinct tests**, run twice in complete 125/129/125/128-test partitions; 0 errors/failures/skips/discovery errors. Incomplete whole-suite wrapper attempts were not counted. All five Git blobs equal exact local source bytes; Python compilation and YAML parsing passed. The source package retains eight complete partition logs/reports, SHA256 manifest, diagnostic and an exact replayable patch.

## Hosted checks and remaining science

An additive `hepta-shared-fanout-research.yml` schedules pinned CPU source tests, one real **stock miniature Transformers** compatibility test, and a separate public-pretrained ModernBERT seven-bank canary. They were queued at publication; no hosted result is inherited from other PRs. The local environment has no installed Transformers, so stock HF/pretrained tests were **not run locally**. Any real-model FLOP ratio must come from the new exact-SHA canary result.

This does not validate reuse across different questions or principals; it does not establish trained cross-task performance, complete resource/energy/latency savings, multi-generation learning, NDU/System2 net benefit, modalities, 1024/4096 native serving, or 10T/100T equivalence. Earlier direct32 fixed-budget public news accuracy (51/64) is one-seed schedule evidence, not topology causality. Existing #1861 real family-split study must be audited separately under its own source SHA.
