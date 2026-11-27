# V8 endpoint-token binding: negative result and cheap structural null

**Research only · DRAFT / SHADOW_ONLY / DENY_ALL.** Stacked on original V7 PR #2352, base SHA 2e7d9c81aec05285ca08c876005e7286d7397d83. This child does not change production model selection, V7 training, NDU/FBSDE runtime, verification authority, or the original V7 failed gates.

## Motivation and mechanism

Original V7's four completed training policies had **0/3** relation-transfer admissions despite 18,000 optimizer updates. This child adds 4,096 parameters to original TokenReader by exchanging token-level messages across different facts, giving **42,562 trainable parameters**, identical in count to V6 BridgeReader and WideReader. It excludes same-fact and padded interactions, zero-initializes the output projection, retains equal common base weights and initial predictions, and uses no label/annotation/world-ID features. Key/value desynchronization is an inference diagnostic only.

The separate structural_null_v8.py implements a label-blind exact parser for the generator's restricted public ownership → storage grammar. It produces an evidence-source proof or rejects unsupported input. It is **not a general natural-language model**. It is an essential inexpensive benchmark for a domain which already admits a deterministic two-hop solution.

## Actual completed local experiment, strictly synthetic

Four arms × three seeds (41/47/53) used **constructed random grammar-token vectors**, not actual pretrained Granite features or V7 learned checkpoints. Fixed 400 Adam updates/arm, 16 training rows/update, total **4,800 optimizer updates / 76,800 training row exposures**. All arms use equal schedules, depth three, CE + 0.5 paired margin, and select only the final fixed checkpoint. No heldout labels choose training depth or hyperparameters. Interrupted monolithic executions are preserved separately and not counted as completed experiments; three isolated seed executions each completed all four arms.

| Arm | Train correct /384 | Old-vocab held /192 | Novel-vocab held /384 | Novel paired both-correct /192 | Training-only CPU sum |
|---|---:|---:|---:|---:|---:|
| Base 38,466 weights | 361 | 92 | 186 | 20 | 7.45s |
| V6 FactBridge 42,562 | 384 | 88 | **197** | 22 | 8.73s |
| V6 Wide Head 42,562 | 373 | 89 | 185 | 12 | 8.14s |
| V8 token EndpointReader 42,562 | 384 | 91 | 182 | 27 | 9.31s |
| Label-blind restricted symbolic null, no learning | 384 | **192** | **384** | **192** | parser time not separately metered |

The same heldout groups are repeated for three initialization seeds and **are not independent observations**. Endpoint does not improve candidate generalization relative to V6 FactBridge; both perform near chance. Higher paired count alone cannot certify new relation transfer. Equal parameter counts and optimizer steps do not imply equal operations, total FLOPs, service cost or energy.

## Verification / provenance boundaries

The exact three GitHub core source blobs (endpoint_v8.py, structural_null_v8.py, test_endpoint_v8.py) were byte-matched against files that passed **11/11 normal and 11/11 Python -O tests** locally. Three additional native-generator test cases passed locally using a **reconstructed** V4 generator module; the remote source-HEAD native generator job has not passed and must not be claimed as executed. The synthetic campaign is retained in the conversation's full downloadable evidence ZIP, not part of original V7 runtime. The bundle includes 12 safetensors final models, per-case prediction vectors, source sets, costs, hash inventories, three independent stdlib scoring reviews and 3,840 same-code actual forward replays with zero numeric difference. The reviewer is independent of the trainer for score arithmetic but not an externally authenticated pretrained runtime.

**Original V7 feedback/fresh gates remain CLOSED. No actual pretrained Encoder call, original V7 retention improvement, FBSDE global theorem, NDU causal gain, true multimodal result, production performance or model promotion is claimed.**

## Decision and next gate

**NO_GO** to substitute V6 FactBridge with this V8 candidate. Before investing in complex System2/FBSDE search, use real frozen Granite token features and genuinely source-disjoint, longer-chain/natural relational tasks, preserve an independently admissible cheap parser baseline, and compare full lifecycle costs. Retain this PR as DRAFT / DENY_ALL.
