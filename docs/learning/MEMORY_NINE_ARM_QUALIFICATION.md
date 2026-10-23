# MemoryCell A–I original-execution qualification protocol

Status: **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. This is an independent
research audit, not model selection, production authorization or scientific proof.

## Frozen nine-arm experiment

| Arm | Required actual execution | Causal question |
| --- | --- | --- |
| A | BM25 over original admitted source frames | Lexical baseline |
| B | Frozen dense Encoder + BM25 + physically executed reranker | Strong hybrid baseline |
| C | Source-grounded Graph-RAG / HippoRAG-style traversal | Graph contribution |
| D | Typed episodic/semantic memory, zero local gradient updates | Typed organization |
| E | Single trained Head attached to genuinely frozen shared Encoder | Local training contribution |
| F | Multiple trained typed Heads using that same Encoder | Differentiation |
| G | F + learned Router selected *before* Head execution | Sparse selection |
| H | G + learned Meta-Graph, with physically measured edge influence | Collaboration |
| I | H + trained Split/Merge vs matching static specialists | Evolution |

Preserve exactly the same source/forget authority and snapshot, frozen
Reader/tokenizer/decoding, original query census, source-family boundaries,
evidence slots, source-frame bytes and resource budgets. Do not assemble
different original research reports into a fictional nine-arm paired result.

The ten predeclared contrasts are B-A, C-B, D-C, E-D, F-E, G-F, H-G,
I-H, I-B and I-C. Primary gate metric is independently adjudicated
**grounded full-answer correctness** (correct answer AND supported citations AND
complete annotated evidence AND actual acceptance), source-family macro
averaged across each of future_1, future_2 and OOD. Raw answer accuracy is
retained as a separate diagnostic. Retrieval-only all-support coverage is diagnostic, not full
answer correctness. Report complete adversarial coverage, calibration,
hallucination, temporal/multi-hop and forget/delete failures.

## Preregistered acceptance fences

- At least 200 independently sourced families **per future_1, future_2 and
  OOD window**, with train/calibration/future/OOD grouping isolation. This
  minimum does not prove statistical independence or sufficient power.
- For each of the ten contrasts in all three windows, a positive paired
  source-family bootstrap lower confidence limit exceeding +0.02 absolute
  answer correctness, with Bonferroni familywise correction across contrasts.
- Matched 8 complete sources, at most 4096 UTF-8 source-frame bytes, at most
  1024 Reader input and 64 output tokens. Same Reader for all A-I arms.
- Resource receipts: original encoder/Head/Reader calls, wall time, RSS,
  resident parameters, indexing, replay and training costs. Budget and
  latency comparison must include full lifetime costs; the current audit
  implements per-row physical counters and the I/B wall-time ratio only.
- Five mandatory causal controls: wrong graph edge, swapped trained Head,
  removed support premise, withdrawn learning ancestor, and dynamic evolution
  versus equal-budget static specialists.
- Source, artifact, optimizer, Router, graph, evaluation and authorizer
  provenance separately authenticated. Hash references or self-reported
  judge IDs are not signatures or verified evidence.

No CI or contract-fixture pass may override these scientific fences.

## Reproducible protocol

Python modules:

- qa/stem-bakeoff/memory_nine_arm_gate.py
- qa/stem-bakeoff/test_memory_nine_arm_gate.py
- .github/workflows/hepta-shared-stem-bakeoff-shadow.yml

The reviewer-only cohort is JSON with schema hepta.memory.nine-arm.v1,
nonempty sources [{group,source_id,frame}] and questions
[{query_id,group,split,question_sha256,answerable,gold_support_ids}].
All source groups must belong to exactly one partition. Gold support IDs
are accessible ONLY to the evaluator; the actual model worker gets a
separately constructed gold-free query/source view.

Before any predictions, precommit metadata with reader_sha256,
source_frontier_sha256, forget_frontier_sha256 and nine arm_specs keys
A through I. Each arm spec contains the exact expected kind from
the Python ARMS registry, a 64-hex artifact_sha256 and a complete
trained_group_ids lineage closure. No trained ancestor can belong to
future/OOD/deletion or adversarial holdouts.

Create the immutable plan with an exclusive write:

    python3 qa/stem-bakeoff/memory_nine_arm_gate.py freeze \
      --cohort /evaluator/cohort.json \
      --metadata /review/arm-metadata.json \
      --output /review/frozen-plan.json

Commit the plan and cohort identities **before** running any model. Hashes
are integrity references, not independent timestamp authorities.

Each real model run emits one JSONL row for each (question,arm) with query,
group, split, ordered selected_source_ids, exact context_sha256 and
context_utf8_bytes, shared Reader/artifact/source/forget digests,
original answer bytes and answer_sha256, strict accepted Boolean,
generation_receipt_sha256, execution_kind=original_model_execution, and
measured nonnegative resources:

    wall_ns, reader_forwards, encoder_forwards, head_forwards,
    peak_rss_bytes, resident_artifact_bytes, input_tokens, output_tokens

Each answer must be sealed before review, then separately adjudicated by
an evaluator-only JSONL record binding query_id, arm, answer_sha256,
Boolean correct/supported, and judge_id. The audit program deliberately
does not treat judge_id as independently authenticated.

Run:

    python3 qa/stem-bakeoff/memory_nine_arm_gate.py audit \
      --plan /review/frozen-plan.json \
      --cohort /evaluator/cohort.json \
      --predictions /sealed/original-predictions.jsonl \
      --judgments /review/independent-judgments.jsonl \
      --output /review/nine-arm-audit.json

It reconstructs delivered evidence from original source frames, rejects
wrong source roots/Reader/model IDs and unexpected rows, accounts for every
missing arm, recalculates support and full-answer metrics, computes the paired
group contrasts and reports the remaining blockers. Its synthetic unit
fixtures attack format and identity enforcement; they are never scored
as actual model observations.

The disposition is **always HOLD_NO_GO** until separately authenticated
owners verify real physical execution, source, independent evaluation,
deletion and cross-platform qualification. The audit cannot certify
cryptographic signatures, causal treatment authenticity or actual GPU TCO.

## Inherited evidence: do not transfer unsupported claims

PR #3125 has real historical LoCoMo retrieval, frozen-Encoder local Head
training, a trained sparse Router and actual split/merge research. However:

- LoCoMo has only ten historical conversational source families; multi-hop
  recall and adversarial abstention remained weak.
- The trained Procedural Head at fixed 0.7 confidence covered substantially
  fewer heldout tasks than frozen-feature nearest neighbor/centroid.
- The learned Router did not consistently beat the pooled strong Head.
- An equal-slot Split lost to static continuation in the second future window.

Those are valuable negative findings, not a nine-arm outcome. Historical
news classification and procedure-selection results cannot be scored as
future memory QA under a common Reader. Never claim all blockers closed
on the basis of those experiments.

Relevant independent stacks: PR #2688 typed MemoryCell contract; #2695
shared Encoder/Head; #3123 durable state/Artifact; #3125 original research.
The LoCoMo source is CC BY-NC 4.0; respect its license and user data
permissions before reexecution.

## Closed only with independent external witnesses

1. All nine actual source-aligned original model predictions, run without
   evaluator gold visible to the candidate.
2. Original Head/Router/graph/evolution and equal-budget static controls,
   physical resource counts and negative-control traces.
3. Independent source, judge, artifact and revocation authorities, including
   reconstructed post-forget state.
4. Prospective independent-family/time/OOD experiments passing precommitted
   simultaneously corrected effects and calibration gates.
5. Exact HEAD terminal required Architecture, blocking CI, platform
   security, recovery and real production owner integration.

Until these conditions are met: SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.
