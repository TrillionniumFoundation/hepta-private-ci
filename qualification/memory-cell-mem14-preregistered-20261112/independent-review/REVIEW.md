# MEM14 independent audit

**Status: VERIFIED_CONSISTENT.**

This audit makes zero model calls and executes no remote commands. Original evidence is read only.

The fixed denominator is 32 source pairs; 320 of 320 planned rows have verified returned evidence.

## Frozen endpoints

| Arm | v2 correct / 32 | Missing | v2 format valid | Strict v1 correct | Relevant memo delivered |
|---|---:|---:|---:|---:|---:|
| on_bm25 | 31 / 32 | 0 | 31 | 0 | 32 |
| off | 0 / 32 | 0 | 0 | 0 | 0 |
| delete | 0 / 32 | 0 | 15 | 0 | 0 |
| replace | 0 / 32 | 0 | 30 | 0 | 32 |
| retrieval_off | 0 / 32 | 0 | 0 | 0 | 0 |
| delivery_off | 0 / 32 | 0 | 0 | 0 | 0 |
| exact_kv | 31 / 32 | 0 | 31 | 0 | 32 |
| finite_icl | 8 / 32 | 0 | 20 | 0 | 8 |
| uniform_replay | 9 / 32 | 0 | 17 | 0 | 9 |
| retention_off | 0 / 32 | 0 | 0 | 0 | 0 |

## Paired causal contrasts

Primary: BM25 minus full memory-off. Missing source outcomes first receive worst-case difference bounds; all 32 pairs remain in the Hoeffding denominator.

Primary one-sided 95% lower bound: **0.536045404**.

| BM25 minus | Wins / losses / ties (complete pairs) | Missing pairs | Mean difference bounds | Nine-contrast simultaneous lower 95% |
|---|---:|---:|---|---:|
| off | 31 / 0 / 1 | 0 | [0.968750, 0.968750] | 0.399048496 |
| delete | 31 / 0 / 1 | 0 | [0.968750, 0.968750] | 0.399048496 |
| replace | 31 / 0 / 1 | 0 | [0.968750, 0.968750] | 0.399048496 |
| retrieval_off | 31 / 0 / 1 | 0 | [0.968750, 0.968750] | 0.399048496 |
| delivery_off | 31 / 0 / 1 | 0 | [0.968750, 0.968750] | 0.399048496 |
| exact_kv | 0 / 0 / 32 | 0 | [0.000000, 0.000000] | -0.569701504 |
| finite_icl | 23 / 0 / 9 | 0 | [0.718750, 0.718750] | 0.149048496 |
| uniform_replay | 22 / 0 / 10 | 0 | [0.687500, 0.687500] | 0.117798496 |
| retention_off | 31 / 0 / 1 | 0 | [0.968750, 0.968750] | 0.399048496 |

## Original bytes and interventions

The four empty-delivery arms have identical request bytes, model-input bytes, tensors and rendered prompts in **32 / 32** sources.

BM25 and exact-KV have identical model inputs in 32 / 32 sources. This comparison exposes whether the baselines deliver the same fact under the single-record budget.

Replacement selects the wrong intervened value in 30 sources; 30 newly follow that value relative to BM25, including 29 changes from the original correct value. These are descriptive intervention checks; original truth and primary scoring stay fixed.

## Measured costs

| Arm | Prompt tokens | Output tokens | Arm wall seconds | Provider wall with setup | Peak RSS KiB |
|---|---:|---:|---:|---:|---:|
| on_bm25 | 3732 | 320 | 157.753171 | 156.843122 | 1143300 |
| off | 3130 | 614 | 166.740926 | 165.932639 | 1143344 |
| delete | 3736 | 471 | 162.573919 | 161.608588 | 1143352 |
| replace | 3732 | 320 | 157.795315 | 156.840818 | 1143464 |
| retrieval_off | 3130 | 614 | 167.008524 | 166.073524 | 1143832 |
| delivery_off | 3130 | 614 | 167.240943 | 166.343374 | 1143320 |
| exact_kv | 3732 | 320 | 157.912128 | 157.015325 | 1143772 |
| finite_icl | 3740 | 442 | 164.528234 | 163.609370 | 1143948 |
| uniform_replay | 3736 | 470 | 163.310762 | 162.411051 | 1143188 |
| retention_off | 3130 | 614 | 167.528822 | 166.548894 | 1143616 |

Common A writer wall time, charged once: 2.491560 seconds. Run wall: 1635.542239 seconds; preparation: 20.778005 seconds.
Per-field observed and missing counts, CPU totals and all per-row evidence pins are retained in REVIEW.json. A missing cost is never treated as an observed zero.

## Scientific scope

Scientific acceptance remains **HOLD**. Production adoption, natural-task benefit and parameter consolidation are not established.

- 32 generated sources share one task template; 320 rows are not 320 independent sources.
- The v2 endpoint was designed after MEM12 but frozen before these new sources generated responses. MEM12 is never rescored.
- A is deterministic ingestion with no model call; retained state uses research Python SQLite, not the production native owner.
- All returned model requests, rendered prompts and tokenizer tensors are checked against original logs and hash bindings; this audit does not retokenize or generate.
- This establishes retained-byte consistency, not authentication of the physical host, observer, original native owner or provider internals.
- Isolation records new network/mount/PID/IPC/UTS/user namespaces and empty task-state roots; system roots and frozen model/runtime assets remain mounted read-only.
- One local model.generate invocation per returned row is evidenced by frozen worker code and one log record; internal forward steps and KV-cache accesses are not observed.
- Equal limits do not imply equal actual costs. Common A cost is charged once; missing costs remain missing.
- Hoeffding bounds assume independent generated sources under this one template. They do not establish natural-task generalization.
- No trained association, parameter consolidation, authenticated production recovery or broad deployment benefit was evaluated.

## Audit identity

Plan SHA256: `1aa291205146cffec039a583640be9c9c33a4afedff8dc31d2cdf32874d4c8e0`.
Source commit: `7f6b5b80cf4528aabd44ad2df1a93d7f70e7590d`; source tree: `491484a45e05d05d2b72fec472f96405c37decac`.
Original durable job: `1a1ced26052-2564-186f`; frozen operation key: `mem14-causal-execute-20261112-ef0c-v1`.
