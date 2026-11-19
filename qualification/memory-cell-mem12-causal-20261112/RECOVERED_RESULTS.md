# MEM12: 80 real generations recovered, no primary memory benefit

## Decision

**The original frozen experiment completed: 80 returned generations, 80 scored rows, no missing rows. Every primary arm scored 0/8. Scientific acceptance remains HOLD.**

This recovers the outcome of the original operation `mem12-causal-execute-20261112-ef0c-v1`. The experiment was not repeated with a new key. The earlier UNKNOWN checkpoint and all timeout responses remain retained. The outer launch acknowledgement has not been invented or inferred from the recovered results.

There are eight paired generated sources, one shared task template and ten interventions. Eighty rows are not eighty independent memory-benefit episodes. A is deterministic ingestion, and this cohort uses the research Python SQLite store; it does not establish ordinary native owner execution or natural-task generalization.

## Primary results under the unchanged public selector

| Arm | Returned / planned | Primary successes | Primary-format matches | BM25-on paired wins / losses / ties |
| --- | ---: | ---: | ---: | --- |
| BM25/RAG on | 8/8 | 0/8 | 0/8 | Reference |
| Full memory off | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Relevant record deleted | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Relevant record replaced incorrectly | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Retrieval off | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Delivery off | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Exact-KV | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Finite-context ICL | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Uniform replay | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |
| Retention off | 8/8 | 0/8 | 0/8 | 0 / 0 / 8 |

All 80 outputs violate the predeclared whole-output format. The original parser, model, actor, cases, arm order, limits and truth labels are unchanged. The report's `[0,0]` difference bounds describe complete observed labels; they are not 95% confidence intervals.

## What the original bytes establish

The complete 159,620-byte original archive was downloaded under one pinned file version, independently checked against SHA256 `29ab6cde66622dd76ebee5cf65ae51c6c17dbbbbe0a66b7b7626d77358782e05`, and extracted only after checking member paths and types. All 1,420 indexed originals match their sizes and hashes.

A separate standard-library-only auditor did not import or execute the experimental implementation. Its status is `VERIFIED_CONSISTENT`, with no inconsistencies found. It checked source and plan pins, A requests and SQLite/snapshots, A exit before fresh C processes, actor inputs/stdout, provider admission, actual requests, raw logs, generation-entry input bytes and tensor shapes, intervention state, scores and costs. Every indexed original had the same hash before and after auditing. The 74 check categories are audit categories, not extra scientific samples or model calls.

For all eight sources, the four empty-delivery arms (`off`, `retention_off`, `retrieval_off`, `delivery_off`) have byte-identical actual requests and model-input records, identical tensors and rendered prompts, and identical output text and token sequences. Their execution paths remain distinct:

- Full off has no reader store and no memory input file.
- Retention off has an empty reader database after the common A write.
- Retrieval off retains state but does not retrieve.
- Delivery off retrieved 16 records across its eight rows but delivered none.

The auditor also verified that deletion removed the relevant record and replacement created the wrong-value second version while leaving the original scoring truth fixed. Withhold remains a delivery intervention, not a complete memory-off implementation.

These checks establish consistency of retained bytes. They do not independently authenticate a production owner or physical host, recompute tokenizer tensors from the tokenizer assets, or observe every internal model forward/cache access. Fixed system roots and runtime remain read-only visible.

## Post hoc diagnosis, explicitly separate from scoring

After inspecting the outputs, a separate exploratory audit counted standalone color words in the response text. This did not change the primary endpoint or any original score.

| Arm | Exploratory text mentions original truth | Relevant key actually delivered |
| --- | ---: | ---: |
| BM25/RAG on | 3/8 | 8/8 |
| Exact-KV | 8/8 | 8/8 |
| Finite-context ICL | 1/8 | 3/8 |
| Uniform replay | 2/8 | 3/8 |
| Delete | 0/8 | 0/8 |
| Incorrect replacement | 0/8 | 8/8, with the wrong value |
| Each of the four empty-delivery arms | 0/8 | 0/8 |

For example, source-01's original truth was `yellow`. BM25 and exact-KV returned `The courier must use a yellow badge.`; replacement returned `The courier must use a green badge.`; full off returned `The courier must use the color badge of the carrier.` All are failures under the frozen one-color primary grammar.

Exact-KV's text contained the correct fact in all eight rows, but the actor did not follow the one-color output instruction. BM25 delivered the relevant key in all eight rows and mentioned the correct color only three times; those remaining failures cannot be attributed to a missing relevant retrieval. They motivate a separately preregistered design, not retrospective relabeling.

Replacement text mentioned the replacement value in three rows, but only two were new changes from the original truth to that wrong value. One unchanged wrong answer already happened to match its later replacement. Another changed answer followed a distractor instead. Counting all three mentions as replacement-caused following would overstate the effect. The full source-by-source table is retained in `independent-review/REVIEW.md`.

## Measured costs

All arms shared limits of two records, 2,048 context bytes, 1,024 input tokens, 32 output tokens and a 60-second model-process deadline. Actual costs differ.

| Quantity | Observed value |
| --- | ---: |
| Input tokens | 9,545 |
| Output tokens | 1,102 |
| Provider wall time including setup, summed over rows | 372.326902 s |
| Arm wall time, summed over rows | 374.529526 s |
| Common A writer wall time, charged once | 0.449167 s |
| Run phase wall time | 375.179779 s |
| Separate preparation wall time | 13.333157 s |
| Model-worker user CPU, summed | 455.914174 s |
| Model-worker system CPU, summed | 20.216432 s |
| Maximum single-worker peak RSS | 1,203,180 KiB |

RSS values are not summed. The run time excludes the separate preparation, archive and readback phases. Archive/readback costs were not independently determined in this bundle. BM25-on used 80 output tokens while off used 152, so their elapsed-time difference cannot establish efficiency superiority. With zero primary successes, cost per correct primary answer is undefined.

## Source and retained evidence

- Execution commit: `811e0e27190066e81a23eebed8ad559ae67d228e`.
- Complete tree: `2043cbf11fd00662cc23562123c27ae4e6f72580`.
- Frozen plan SHA256: `f623a23197fe94b3d5434ffac1f02cb3d99398ca4c69aad18716dbeeef1b2d82`.
- Original complete archive: `run-original.tar.xz`, SHA256 `29ab6cde66622dd76ebee5cf65ae51c6c17dbbbbe0a66b7b7626d77358782e05`.
- Independent audit JSON: SHA256 `b0a5bb215552fce52575852c0234d50115af53bf608f6f547d8b88ca2adeb97c`.

`RUN_SUMMARY.json` is the unchanged remote summary. `RECOVERY_EVIDENCE.json` indexes the recovered deliverables. The full raw provider requests, model inputs, logs, A databases, plan and frozen execution source live inside the original archive. The earlier `checkpoint.tar.xz` is retained unchanged.

To reproduce the independent audit in a new scratch directory, place the archive there as `evidence.tar.xz`, extract it into a sibling `original/` directory, copy `independent-review/` alongside it, and run `python independent-review/review.py`. That auditor reads the originals and writes only its own review outputs. Do not execute the model runner to reproduce an audit.

No learned association, parameter consolidation or production adoption follows from this negative primary result. Any new experiment must use fresh sources and freeze its own grammar, context budget and analysis before generation; it must preserve this cohort's zero scores and cannot treat cross-cohort design changes as a causal contrast.
