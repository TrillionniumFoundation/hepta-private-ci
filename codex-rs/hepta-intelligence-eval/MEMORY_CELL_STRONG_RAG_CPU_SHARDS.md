# MemoryCell: independently replayable frozen-reader CPU shards

**Scope:** research-only, eight authored development cases; no model adaptation, production qualification, independent test family, new benchmark label, or semantic truth certificate.

## Why one CPU job cannot complete

The actual [GitHub Actions run 38111452963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963) for original source `02c12b4aff0d589d10e5ed25d22b05d794ca96a0` reached a real, pinned Qwen2.5-3B-Instruct reader (revision `82f42baa094a9600e39ccd80d34058aeeb3abbc1`). Its job was cancelled after nearly three hours while calibration was still incomplete. Downloaded [artifact 11696974258](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963/artifacts/11696974258) has ZIP SHA-256 `129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8`, complete inner `SHA256SUMS`, exact original tested commit, and **four** fsynced raw generation receipts:

| Existing frozen arm | Input tokens | Actual Qwen CPU seconds |
| --- | ---: | ---: |
| `k1` | 504 | 923.308 |
| `k2` | 787 | 1457.513 |
| `k3` | 1076 | 2045.598 |
| `k4` | 1370 | 2641.516 |

Those four calls took **7067.934 seconds (117.799 minutes) of model time alone**. They do not complete the five-arm calibration for even one original question. The old 180-second single-call viability threshold would reject this CPU host; the new design instead bounds each *individual* shard generation at 5400 seconds and allocates separate 360-minute jobs. It does not claim CPU has become inexpensive. GitHub runner capacity, 32 separate staging downloads and total cost remain explicit blockers to practical execution.

## Exact registered job census

Run the original source and frozen reader without changing its original decoder, original event bytes, task labels or prompt-token budget. The 16 calibration shards are eight cases times these **disjoint** arm groups: `k1,k3,k6` and `k2,k4`. The 16 evaluation shards are eight cases times: `selected_k,hybrid_k4,single_hop,organized,empty` and `hybrid_k6,hybrid_k4_reversed,entity_time,program_support`.

Each job stages the same published Qwen revision and verifies the original model-file inventory digest. A time-varying publisher-stage duration is retained per job; the common frozen policy uses one canonical **actual** staged model metadata file and independently verifies the shared inventory across all shards. No model weights are uploaded as workflow artifacts. Public calibration jobs only receive frozen calibration questions/sources and a requirements lock, **not** test answer labels or the original test input ZIP.

Every generated answer, failure, source receipt and citation queue is journaled with durable flush before any scoring. Only after the *full* 40-answer calibration shard census is present and each answer model/source/hash verified does a distinct collector read calibration labels, re-execute the strict scorer/program worker, run eight-fold leave-one-out sensitivity and freeze a top-k choice (task success, lower input-token cost, lower k). Any missing, failed, duplicate or modified attempt rejects the collector.

Only the frozen policy is then shown to the nine-arm evaluation shards, which each re-run the original `EventPresentationReader` and preserve its source order and citation protocol. After all **72/72** original outputs exist, another collector opens test labels, verifies the single-hop selection, scores real worker actions, computes paired contrasts, tracks identical-prompt disagreements and audits formal citation-chain coverage.

The final output includes every shard's raw JSONL, stage file, reader inventory, runtime metadata, exact SHA pins, both complete aggregated raw journals, independently computed task reports, the original source SHA, and one complete top-level `SHA256SUMS`. `strong_rag_shards.py verify-release` reconstructs **every** raw answer from the original per-shard files and refuses drift. The existing separate `strong_rag_receipt.py` independently rechecks original evidence, citation queues, task scoring and policy effects. Neither replay invokes a pretrained reader, signs semantic entailment, fabricates independence, or admits a production candidate.

## What this does not prove

The 32 CPU jobs can be expensive and GitHub may not schedule them promptly. A passing test suite, source inventory, per-shard replay or even all 112 authored-task generations establishes neither an independent task population nor parametric memory superiority. Qwen weights remain research-only under the existing license and **are not serialized into any Actions artifact**. No production writer/reader, authorization, external observer, migration or rollback is enabled.

**Acceptance gate:** exact-source completed 40/40 calibration + 72/72 evaluation + independently replayed, non-mutated answer/source provenance + qualified external real tasks. Until then: `candidate_accepted=false`, `statistical_superiority=false`, and `production_accepted=false`.

## Qualified hosted CPU shards before any model staging (2026-10-12)

The original CPU monolith's 180-minute timeouts were confirmed from downloaded
raw journals, not inferred from queue state: only the first four of forty
calibration answers completed, requiring 923.308, 1457.513, 2045.598 and
2641.516 model seconds. The original reader-model/prompt contract is preserved.
The separate four-run exact-output audits have since recorded 448 real
responses and a NO-GO on incremental organizer accuracy/citation gains for
the original authored population. These repeats do not create fresh tasks.

Both sharded model phases now explicitly request `ubuntu-22.04`, matching
the hosted BF16 scout's only positive image observation, and install the
original pinned Python 3.12 interpreter before installing the CPU torch
and model dependencies. On **each newly allocated matrix VM**, before
downloading pretrained weights, the existing `strong_rag_host_gate.py`
tests the actual Linux CPU records, architecture and accelerated BF16
instruction support. The source commit and resulting eligibility receipt
are uploaded in a separate per-shard host artifact even if the check fails.
An unsupported host fails closed; it is not automatically relabeled or
replaced with CUDA, FP32, quantization or a different reader.

The full 8-case x 2-part matrices, disjoint 40 and 72 original answer
censuses, calibration/test label separation, original weights and token
budgets, immutable response journaling, cost accounting and independent
replay retain their existing gates. Per-shard host receipts are diagnostic
and do not substitute for SHA-sealed final answer provenance or an
independent semantic evaluator. `ubuntu-22.04` is a runner **image label**,
not a reservation of BF16-capable hardware: a later allocation can still
fail the gate. No Qwen calls or production claims are made by this CI fix.
