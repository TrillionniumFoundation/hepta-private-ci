# MemoryCell frozen-reader multi-metric Pareto audit

**Status: retrospective, source-pinned diagnostic; not an experimental
qualification, statistical proof, or production acceptance.**

## Evidence provenance

This note combines the **same 96 original model generations** from
generating commit `59f9eadd5cc919359079e04442f7343838a60057`: Qwen2.5-3B
and SmolLM2-1.7B, each with eight authored questions and six conditions.
The frozen plan is `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.

Machine-readable, independently replayed measurements:
[historical-frozen-reader-multimetric-pareto-20261011.json]
(../../scripts/memory_cell/data/historical-frozen-reader-multimetric-pareto-20261011.json).
The source Qwen archive ZIP SHA-256 is
`831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98`;
the Smol archive ZIP SHA-256 is
`67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae`.
All 42 inner archive files and every original raw/scored pair passed
read-only integrity checks. Four local replay tests also passed, including
rejecting altered answers and wrong archive digests.

## Four dimensions on exactly matched reader and questions

Correct + cited-chain measures require **both** strict task success and
a complete formally connected public event path from cited original IDs.
This is a deterministic event-schema check, **not** semantic entailment
review, independently certified sufficiency, or a 99% citation guarantee.
Times are summed model-read seconds in historical receipts, not end-to-end
latency, cloud bills, or total lifecycle costs.

| Reader | Source-only condition | Correct / 8 | Correct with full cited chain / 8 | Prompt tokens | Reader seconds |
| --- | --- | ---: | ---: | ---: | ---: |
| Qwen 3B | Hybrid top-4 | 3 | 1 | 10,806 | 120.382 |
| Qwen 3B | Entity/time, full path | 8 | 4 | 5,752 | 75.880 |
| Qwen 3B | Organized with correction pruning | 8 | 4 | 5,179 | 71.234 |
| SmolLM2 | Hybrid top-4 | 1 | 0 | 11,767 | 134.725 |
| SmolLM2 | Entity/time, full path | 2 | 0 | 6,195 | 74.874 |
| SmolLM2 | Organized with correction pruning | 3 | 0 | 5,560 | 68.158 |

**Within the Qwen historical set:** organized saves 573 prompt tokens
(9.96%) compared with entity/time while achieving the **same** 8/8
strict-correct and **same** 4/8 correct-and-cited-chain count. Reader-time
sums are 4.646 seconds lower, but this tiny uncontrolled sample does not
establish reliable runtime superiority or a source-family-independent
model-capability benefit.

**Within the Smol set:** organized gains one strict-correct answer and
saves 635 prompt tokens relative to entity/time, but both have **zero**
correct answers with complete formally cited public paths. Smol's
task-accuracy gain is not a citation-quality gain.

## Descriptive Pareto, not causal superiority

An annotation-blind condition descriptively dominates another only if,
under the SAME reader: strict-correct and complete-chain counts are no
lower, prompt tokens and reader seconds are no higher, and at least
one inequality is strict. The allowed conditions are `empty`, `hybrid`,
`entity_time` and `organized`. **Do not admit** `program_support` or
`without_prerequisite` into the fair baseline frontier: they use
program/answer-dependent evidence manifests.

On these eight historical questions and four dimensions, `organized`
descriptively dominates both `entity_time` and `hybrid` for each reader.
`empty` is also mathematically non-dominated only because it uses
the fewest tokens: it answers **0/8** questions correctly and is not
a useful memory policy. None of these retrospective frontiers qualifies
MemoryCell for production or proves generalization.

## Next hard gates

- Finish the **new** source-pinned reader experiment: 40 actual top-k
  calibration generations, 72 actual nine-arm test generations, then
  independent original-answer and formal-citation replay.
- Compare `single_hop`, full-path `entity_time`, and correction-aware
  `organized` independently; the historical `entity_time` condition
  already traverses full paths and must not be renamed as single-hop.
- Retain failed/absent calls in the planned denominator; count full
  prompt tokens, original source/index storage, calibration, ongoing
  maintenance, revocation and recovery, rather than claiming an
  unmeasured end-to-end cost saving.
- Require independent source families, future time windows, human
  semantic adjudication and production-specific reliability before
  any parameter-memory superiority or operational acceptance claim.

All admission flags remain **false**. This document does not regenerate
answers or infer unknown single-hop task outcomes.
