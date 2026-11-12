# MEM14: preregistered controlled memory benefit

## Decision

**The original run returned and scored all 320 planned generations, with no missing or UNKNOWN rows. An unchanged, outcome-blind independent auditor verified all retained originals and recomputed the results with zero inconsistencies.**

Under the new study's preregistered v2 endpoint, BM25 memory-on scored **31/32**, versus **0/32** for full memory-off. The source-paired difference is **0.96875**: 31 wins, zero losses, one tie. Its preregistered one-sided 95% Hoeffding lower bound is **0.5360454043494287**. The nine-comparison Bonferroni lower bound is **0.39904849642059204**.

This establishes a positive controlled result for 32 fresh generated sources under one task template. It is not broad production acceptance. A is deterministic ingestion, this cohort uses research Python SQLite, and the actual model is the frozen SmolLM2-135M-Instruct profile. Native-owner benefit, natural-task generalization, authenticated observer custody and parameter consolidation remain unestablished. **Global scientific acceptance and production adoption remain HOLD.**

## Frozen design and the preserved negative result

MEM12's original 80 rows remain unchanged: all ten arms scored 0/8 under its frozen v1 grammar. Its full original archive, negative result and independent review remain in `qualification/memory-cell-mem12-causal-20261112/`. No old row was relabeled or regenerated.

After that measurement failure, MEM14 was registered as a separate study with 32 new sources and a common single-record cap. The actor bytes, local model, worker and runtime profile are identical to MEM12. Its new v2 public parser accepts a bare color, bare UNKNOWN, or exactly `the courier must use a <color> badge.` after stripping and case folding. UNKNOWN is a valid format but never the correct color. The parser has no expected-answer input.

The complete actual plan and pin were published in commit `fe11230642106872a71c7cc1f1d131a0abfbbb14` before generation. All ten arms share one record, 2,048 context bytes, 1,024 input tokens, 32 output tokens and a 60-second model-process deadline. The original cohort's two-record limit and v1 parser were not changed. The two cohort outcomes are not a causal contrast between designs.

The old v1 endpoint was also retained as a descriptive endpoint in the new study: **all 320 new outputs still score zero under v1**. Memory improves the measured factual response under v2; the actor's original output-format requirement remains unsatisfied. The one BM25/exact-KV v2 failure says `the orange badge`, outside the frozen `a <color> badge.` grammar. It remains a failure; the parser was not loosened.

## Results

Every arm returned and scored 32/32 rows with no missing labels.

| Arm | v2 correct / 32 | v2 format accepted / 32 | v1 descriptive correct / 32 | Relevant memo delivered / 32 |
| --- | ---: | ---: | ---: | ---: |
| BM25 memory-on | 31 | 31 | 0 | 32 |
| Full memory-off | 0 | 0 | 0 | 0 |
| Relevant record deleted | 0 | 15 | 0 | 0 |
| Relevant record replaced incorrectly | 0 | 30 | 0 | 32, containing the replacement |
| Retrieval-off | 0 | 0 | 0 | 0 |
| Delivery-off | 0 | 0 | 0 | 0 |
| Exact-KV | 31 | 31 | 0 | 32 |
| Finite-context ICL prefix | 8 | 20 | 0 | 8 |
| Uniform replay | 9 | 17 | 0 | 9 |
| Retention-off | 0 | 0 | 0 | 0 |

The baseline comparison uses identical limits, one actor and one public parser. BM25 and exact-KV produce byte-identical model inputs and outputs in all 32 sources. This experiment provides no advantage of BM25 over exact-KV. Finite ICL and uniform replay expose different single-record selections; they delivered the relevant fact in eight and nine sources respectively.

## Paired estimation

The independent unit is a source, not one of the 320 intervention rows. Each paired difference lies in `[-1,1]`. With the fixed denominator of 32, the primary radius is `sqrt(2*ln(20)/32) = 0.43270459565057134`; the nine-comparison radius is `sqrt(2*ln(180)/32) = 0.569701503579408`. Missing pairs would first receive worst-case per-source bounds and remain in the denominator. No pairs were missing.

| BM25 minus comparator | Wins / losses / ties | Mean difference | Simultaneous one-sided 95% lower bound |
| --- | --- | ---: | ---: |
| Full off | 31 / 0 / 1 | 0.968750 | 0.399048496 |
| Relevant deletion | 31 / 0 / 1 | 0.968750 | 0.399048496 |
| Incorrect replacement | 31 / 0 / 1 | 0.968750 | 0.399048496 |
| Retention-off | 31 / 0 / 1 | 0.968750 | 0.399048496 |
| Retrieval-off | 31 / 0 / 1 | 0.968750 | 0.399048496 |
| Delivery-off | 31 / 0 / 1 | 0.968750 | 0.399048496 |
| Exact-KV | 0 / 0 / 32 | 0.000000 | -0.569701504 |
| Finite ICL | 23 / 0 / 9 | 0.718750 | 0.149048496 |
| Uniform replay | 22 / 0 / 10 | 0.687500 | 0.117798496 |

These are intervention contrasts holding the other parts of this pipeline fixed. Their repeated positive differences are not additive component contributions. The bounds assume independent generated sources from the one frozen task template and do not establish natural-task generalization.

## What the original bytes establish

The 597,704-byte original archive was recovered in ten chunks bound to one immutable file version. Its whole SHA256 is `36c1526898eb7c117e013c0235cfa322fcc46790f984fa330302cbbf0be4821b`. The archive contains 5,597 indexed original files plus the index itself. Safe extraction checked member paths and types. The independent audit checked every indexed length and hash before and after its read-only examination.

The audit did not import or execute the experimental implementation, load a model, retokenize or issue remote commands. Its three modules were frozen in `independent-audit-ready.tar.xz` before it read this study's outcomes; the completed run needed no audit-code repair. It verified the source/plan/helper bindings, writer request and SQLite state, original snapshots, A's actual exit before fresh C execution, independent retrieval reconstruction, actor inputs/output, provider admission, exact provider request, raw model log, generation-entry rendered prompt and tensors, scores, contrasts and cost accounting.

The four empty-delivery arms have identical actual request bytes, model-input bytes, rendered prompts, tensors and outputs in **32/32** sources. Their mechanisms are distinct:

- Full off creates no reader store and supplies no memory input file.
- Retention-off supplies an empty reader database after the common A write. It does not save that already-incurred A cost.
- Retrieval-off retains the source state but performs no retrieval.
- Delivery-off selects the record and suppresses its delivery.

All task-specific C/model workers use fresh network, mount, PID, IPC, UTS and user namespaces and empty task-state roots. Frozen model/runtime assets and system roots remain mounted read-only. The evidence closes the tested old-chat, task-file, tool and cache routes at this model-worker boundary. It does not authenticate a physical host or trace every internal model forward step and KV-cache access.

Deletion removes the relevant record. Replacement creates the wrong-value version while keeping original truth fixed. The replacement response selects the new wrong value under v2 in 30/32 sources: 29 are changes from an originally correct value, and one was originally unscored by the format rule. The remaining two replacements fail the frozen format. All replacement rows remain primary failures; merely mentioning a wrong value is not substituted for a paired causal switch.

## Measured costs

Equal limits do not mean equal actual token, setup or elapsed costs. Common A cost is reported once, and all 320 returned rows have observed per-row cost fields. No monetary or energy cost is inferred.

| Arm | Input tokens | Output tokens | Arm wall seconds | Provider wall including setup |
| --- | ---: | ---: | ---: | ---: |
| BM25 on | 3,732 | 320 | 157.753171 | 156.843122 |
| Full off | 3,130 | 614 | 166.740926 | 165.932639 |
| Delete | 3,736 | 471 | 162.573919 | 161.608588 |
| Replace | 3,732 | 320 | 157.795315 | 156.840818 |
| Retrieval-off | 3,130 | 614 | 167.008524 | 166.073524 |
| Delivery-off | 3,130 | 614 | 167.240943 | 166.343374 |
| Exact-KV | 3,732 | 320 | 157.912128 | 157.015325 |
| Finite ICL | 3,740 | 442 | 164.528234 | 163.609370 |
| Uniform replay | 3,736 | 470 | 163.310762 | 162.411051 |
| Retention-off | 3,130 | 614 | 167.528822 | 166.548894 |

Totals are 34,928 input tokens and 4,799 output tokens. Provider wall including setup sums to 1,623.226707 seconds; arm wall sums to 1,632.392743 seconds. The run phase took 1,635.542239 seconds, separate preparation 20.778005 seconds, and the common A writers 2.491560 seconds charged once. Model-worker CPU sums to 1,875.439691 user seconds and 90.790315 system seconds. Maximum single-worker RSS is 1,143,948 KiB; peaks are not summed. Archive/readback phase costs were not separately observed and remain null. Output lengths differ, so the elapsed-time table alone is not an efficiency-superiority result.

## Source, recovery and independent reproduction

- Execution commit: `7f6b5b80cf4528aabd44ad2df1a93d7f70e7590d`; full tree: `491484a45e05d05d2b72fec472f96405c37decac`.
- Frozen plan SHA256: `1aa291205146cffec039a583640be9c9c33a4afedff8dc31d2cdf32874d4c8e0`.
- Original operation: `mem14-causal-execute-20261112-ef0c-v1`; durable job: `1a1ced26052-2564-186f`.
- Original terminal: succeeded, exit 0, not timed out, complete/durable output and confirmed terminal publication. The original 914-byte SDK payload has SHA256 `c50ac7cc52fabb6216d08dff7a51d19c594a8c507a49e0449d8bfb315a534a62`.
- `run-original.tar.xz`: the unchanged experiment archive.
- `RUN_SUMMARY.json` and `ARCHIVE.json`: unchanged original remote files, recovered from an immutable SDK payload with independently verified SHA256.
- `independent-audit-ready.tar.xz`: fixed audit modules and pre-outcome preparation checks; SHA256 `6f52a4dd937d866789a0d8c7d23149d33e87373e3ccc50b548b43b9f6f3b4ae3`.
- `independent-audit-completed.tar.xz`: complete audit JSON/Markdown, audit execution, original transfer envelopes, safe-extraction checks and readback metadata; SHA256 `f37b8560dc79e86bbd5351c17164d4b62ca8d6e2bb4a9398412701a6c6ad02c4`.
- Independent `REVIEW.json`: 559,774 bytes, SHA256 `4ba559ea58fb3e1d971a87271ae800018dece4de46c78ce49292d37c26ad5502`; readable report reproduced in `independent-review/REVIEW.md`.

Initial launch/transport timeouts and same-key recovery records remain retained. Recovery did not repeat the model experiment. Extract the ready audit package and original archive into separate new directories, then use the ready package's README command with the exact archive hash and length above. The audit writes only its own new output directory and does not rerun the model.

`COMPLETED_METADATA_CHECKPOINT.json` and the earlier admission/audit checkpoints describe their own observation times and are preserved unchanged. The current result is the completed independent audit documented here and in `EVIDENCE.json`.

No trained association, slow parameter consolidation, native-owner scientific promotion, merge or production adoption follows automatically from this controlled result.
