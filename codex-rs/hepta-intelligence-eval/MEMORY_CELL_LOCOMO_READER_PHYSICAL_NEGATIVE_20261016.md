# MemoryCell original Smol135 four-regime LoCoMo negative — 2026-10-16

**Research-only physical inference complete; MemoryCell and production DENY_ALL.**

## Original artifacts and actual execution

Original frozen original-weight Smol135 FP32 Reader: Git source blob
c9567b43e5d15ca428baeb3a972b70435bcc7ed7 (offline_smol_reader.py).
Model artifact ID 11586991191 has outer ZIP SHA-256
07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af,
and weight SHA-256 5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c.
Public previously exposed original LoCoMo JSON SHA-256
79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4.
The isolated original Reader used Torch 2.10.0+CPU, not proven numerically
equivalent to the historical Torch 2.5.1 or official HF runtime.

Eight distinct published conversation root proxies were selected with a
precommitted hash order and one question per root. The source preparation
inspected publisher annotated evidence IDs but not target answer text.
Every frozen Reader arm retained the same prompt, original weights and tool
permissions, with <=1200 input tokens and <=24 generated tokens.
Conditions: no evidence, lexical BM25 Top-3, publisher-annotated witness plus
two question-only ranked distractors, and deletion of that publisher witness.
The publisher annotation is not independently human-certified sufficient
context and does not by itself entail the answer.

Original run code Git blob 72ec79ef98f3916c86390db8d8f9725446301ff1
is retained **exactly** as physically executed, without posthoc formatting.
21 original model attempts were individually fsynced before the first process
interrupted. A separately checked local recovery process preserved their
exact original SHA-pinned 21-row prefix and completed 11 additional original
model calls, also fsynced. The resulting sealed original raw answer journal
SHA-256 is 1e36a1dcfefabf8d8912b81e215a9e7383bc4eb08a63e2dc592a0b46ce65aab3.
This is a one-host journal resume, not distributed MemoryCell recovery.
Original raw questions, model weights, target answers and per-answer text are
not committed to public Git.

Only AFTER closing the full 32-row original-answer journal did the scorer
open original publisher labels. A separate, model-free verification process
re-opened original dialogue bytes for all 32 task conditions and recomputed
the structural citation and strict/token-F1 metrics. Independent reviewer
source code Git blob: 4da31dfac6f2eb806c252548e719a5107193121a.
That process did not rerun neural logits and does not authenticate original
model-host execution.

## Original physical generated-answer results

| Condition | Actual original calls | Strict task success | Mean diagnostic token-F1 | Structurally valid citation |
| --- | ---: | ---: | ---: | ---: |
| No evidence | 8/8 | 0/8 | 0.0208333 | 0/8 |
| BM25 Top-3 | 8/8 | 0/8 | 0.0125000 | 0/8 |
| Publisher annotated witness | 8/8 | 0/8 | 0.0125000 | 0/8 |
| Missing annotated witness | 8/8 | 0/8 | 0.0125000 | 0/8 |

Zero emitted citations means human-semantic citation precision is UNDEFINED,
not 0 or 100 percent. There are no autonomous original-repository program tasks,
stronger reference Reader calls, independently observed future source families,
external sufficient-evidence judgments, trained parameter-memory weights or
complete lifecycle total costs. This small published-data and 24-token-budget
study does not establish universal Reader incapacity.

Sanitized original model report Git blob:
daea9baf005f489720f4181cc7073d950bf3afaa
(file SHA-256 82aeed889a72597667e6cf613eac48d778f4347a24ca812ee3ff7c2f769d52c6).
Model-free original source/citation QA replay Git blob:
1b0dfafe8f4f2fe446cf93c5dac5b66585645b8d.
Read-only admission verifies these exact source blobs plus all model call
counts, token costs, raw journal SHA and NO-GO flags. Nine source-only
adversarial tests passed in the isolated local workspace; hosted exact-head
CI must pass separately.

## Reproduction

Use SHA-verified model and published LoCoMo assets with the original
offline_smol_reader.py in a complete repository checkout:

- python3 scripts/memory_cell/locomo_reader_four_regimes.py prepare LOCOMO.json RUN_DIR
- python3 scripts/memory_cell/locomo_reader_four_regimes.py execute RUN_DIR MODEL_DIR
- python3 scripts/memory_cell/locomo_reader_four_regimes.py score LOCOMO.json RUN_DIR NEW_REPORT.json
- python3 scripts/memory_cell/locomo_reader_replay.py LOCOMO.json RUN_DIR NEW_REPORT.json --raw-sha256 RAW_SHA --report-sha256 REPORT_SHA --output NEW_REPLAY.json
- PYTHONPATH=scripts/memory_cell python3 -m unittest discover -s scripts/memory_cell -p test_locomo_real_evidence_gate.py -v

Original execute is create-only and does not resume a partial existing
journal by itself. The observed real recovery required an independent checked
local process; it is not a committed general-purpose recovery mechanism.
The GitHub Actions workflow runs no new neural model calls and cannot turn a
source-only replay into independent neural attestation.

## Admission

Actual fixed Reader delivered no strict-correct tasks in this small cohort,
including publisher-witness condition. This directs research toward
independently reviewed sufficient evidence and stronger frozen Reader
diagnosis BEFORE parameter-memory training. New authentic source-family
future windows, matched Reader/tool rights, real program execution, semantic
entailment and total extraction/index/storage/train/query/revoke/recover
economics remain necessary. Blocking-ci, Architecture, HNMF, DecisionCell,
CNS and FinalUse gates are unchanged. No main merge or default deployment.
**production_accepted=false**.
