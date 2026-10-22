# Actual LoCoMo source-memory retrieval — 2026-10-22

The retained experiment evaluates memory retrieval against original conversation
evidence, rather than news labels. Source-preserving episode organization helps
the aggregate support-retrieval metric in this limited experiment, while **the
multi-hop slice regresses and the Meta abstention screen fails**. This is an
untrained sparse-retrieval experiment. It does not establish learned MemoryCell
benefit, typed production integration, answer accuracy or a general memory system.

## Source, grouping and frozen protocol

- Original [LoCoMo release](https://github.com/snap-research/locomo), commit
  `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376`.
- `data/locomo10.json`: 2,805,274 bytes; SHA-256
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`;
  Git blob `d95b872480b413d935821fdc3c84f8a8f5f29e73`.
- Authors: Adyasha Maharana, Dong-Ho Lee, Sergey Tulyakov, Mohit Bansal,
  Francesco Barbieri and Yuwei Fang. See the original ACL 2024 release and its
  [CC BY-NC 4.0 license](https://github.com/snap-research/locomo/blob/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/LICENSE.txt).
- All 1,986 questions, 5,882 original dialogue turns and ten conversations are
  retained. The corpus is generated conversational benchmark data; it is not
  authenticated production-user experience.
- A fixed SHA-256 ordering assigns two complete conversations to development,
  two to calibration and six to evaluation. Conversation IDs never cross splits.
  No exact normalized text of at least ten words crosses conversation groups in
  this corpus. Near duplicates and actual statistical independence are not proven.
- `plan.json` is written and fsynced before index construction and retrieval.
  `selection.json` freezes development and calibration decisions before any
  evaluation scoring. Both bind the exact generating Python source hashes.

| Split | Original conversations | Questions |
| --- | --- | ---: |
| Development | conv-30, conv-41 | 298 |
| Calibration | conv-26, conv-44 | 357 |
| Evaluation | conv-47, conv-42, conv-48, conv-43, conv-49, conv-50 | 1,331 |

This benchmark was used in earlier project development. These are isolated
partitions for this frozen experiment, **not newly collected independent future
windows or a previously unseen final benchmark**. The ten source groups do not
become thousands of independent samples through question counts.

## Actual execution and matched bounds

All strategies use SQLite FTS5 BM25 with Porter/Unicode tokenization over only
the original dialogue text, speaker and session timestamp. Generated observations,
session summaries, event annotations, image captions and answer strings are not
retriever inputs. Original question category and gold evidence IDs exist only in
the scorer. The independent input-mutation test confirms that changing them cannot
change the retriever's corpus, query or prediction.

Every arm has the same maximum **eight original turns and 4,096 UTF-8 bytes**,
including the delivered source-ID, speaker and timestamp frames. These are byte
measurements, not tokenizer counts. No source frame is partially truncated.

1. **Raw-turn BM25:** ranked original turns.
2. **Turn + session BM25:** reciprocal-rank fusion of turn and session rankings.
   The fusion weight is selected from 0, 0.25, 0.5, 1 and 2 using development
   conversation-macro all-evidence recall, then partial recall. Weight 2 wins.
   This is the stronger sparse control within this registered family; it is not
   an exhaustive dense/reranked or state-of-the-art baseline.
3. **Episodic context:** the same frozen fused ranking followed by bounded
   preceding/following-turn expansion within each original timestamped session.
   It preserves sources and speakers. It does not infer new semantic Facts.
4. **Episodic + Meta screen:** reuse the identical episodic result and apply a
   lexical-coverage threshold selected on calibration groups. The screen only
   offers or withholds context; it never authors facts or invokes procedures.

There are 1,847 development/calibration retrieval calls and 5,958 census retrieval
calls. The Meta arm reuses episodic outputs. LLM calls, model downloads, gradient
updates and procedural executions are all zero. Index construction took 55.71 ms
in this run. The two-index serialized storage is 3,887,104 bytes; the retained
2,805,274 original source bytes are also counted. No compression claim is made.

## Evaluation result

The 1,331-question evaluation census contains 1,022 support-scorable cases,
299 adversarial cases and ten missing/unresolved evidence annotations. Across
the full 1,986-question census there are 1,527 support-scorable cases, 446
adversarial cases, nine unresolved-reference cases and four missing-reference
cases. Every question remains in its planned denominator and per-category ledger.

"All evidence" means all IDs in the supplied gold annotation set were retrieved.
It does not prove that every listed ID is necessary or that the set is sufficient
for a correct answer. These are custom retrieval diagnostics, not official QA
accuracy, semantic citation entailment or an independent correction of the gold.

| Arm | Mean gold-support recall | All gold IDs retrieved | Conversation-macro all gold |
| --- | ---: | ---: | ---: |
| Raw-turn BM25 | 59.48% | 54.11% | 54.02% |
| Turn + session BM25 | 62.63% | 57.05% | 56.92% |
| Episodic context | 67.26% | 61.84% | 61.85% |
| Episodic + Meta screen | 67.26% | 61.84% | 61.85% |

The primary conversation-macro difference is **+4.924 percentage points**.
The descriptive 95% paired bootstrap interval is [+1.495, +9.078] points, using
4,000 resamples of the **six whole evaluation conversations**. Source independence
is unauthenticated, power is limited and comparisons are not multiplicity-adjusted.
The report therefore keeps `superiority_established=false`.

### Task differences matter

| Original category | Planned / support-scorable | Strong sparse: all gold | Episodic: all gold |
| --- | ---: | ---: | ---: |
| 1, multi-hop | 178 / 175 | 13.71% | **10.29%** |
| 2, temporal | 207 / 206 | 61.65% | 64.56% |
| 3, open-domain | 68 / 63 | 26.98% | 28.57% |
| 4, single-hop | 579 / 578 | 71.80% | 80.10% |
| 5, adversarial | 299 / 0 | Not a positive-support target | Not a positive-support target |

The aggregate improvement is primarily single-hop context recovery. Neighbor
expansion can consume slots needed by distant evidence; the observed multi-hop
regression remains a blocker. No parameter or topology has been retuned on these
evaluation results.

Calibration selects Meta threshold **0**, so every evaluation question receives
context, including all 299 adversarial questions. Answerability balanced accuracy
is **0.50**. Lexical coverage did not establish useful abstention. Retrieving a
relevant-looking passage does not establish that a question is answerable.

The original dataset has 910 image-referencing turns. Images are not downloaded
or decoded. `evidence_has_image` slices are retained in the report; an image URL
or the presence of nearby text does not certify sufficient multimodal evidence.

## Resource and implementation limits

Maximum observed context size is 2,641 bytes; the eight-turn cap usually binds
first. Mean delivered bytes are 1,579 for raw-turn BM25, 1,604 for fusion and 1,567
for episodic organization. Their observed query p95 values are approximately
1.19, 1.36 and 1.50 ms on this shared CPU process. These include local indexing
lookups and context framing, exclude remote serving/queueing, and are not target
host performance or equal-total-compute claims. Python is 3.12.14 and SQLite is
3.53.1. Original data and index storage remain part of lifecycle cost.

The Rust `MemoryCellRoleV1` dispatcher, SQLite typed admission, durable host
witness, learned parameter memory, cross-node runtime, source correction/deletion,
and procedure preconditions/effects are not exercised here. Semantic and Procedural
Cells remain unqualified. This research result is `DENY_ALL` with production
activation disabled.

## Retained evidence and reproduction

- `plan.json`, `selection.json` and `report.json` retain the complete protocol,
  all candidate selection scores, all split/category/source-group results,
  physical byte counts and source/code identities.
- Ten deterministic gzip ledgers retain all **7,944 question × arm records**,
  including original question digests, chosen source IDs, delivered-context
  digests, actual byte counts, categories, unresolved references and scores.
- `audit.json` is a separate implementation's replay: it imports no experiment
  module, reconstructs all 7,944 contexts from original source turns, and
  verifies hashes, budgets, denominators and support metrics. This is a same-session
  computational check, not an external evaluator signature or human adjudication.
- Seven behavioral tests cover actual FTS behavior, source/gold separation,
  scope isolation, UTF-8 budgets, unresolved annotations and cluster pairing.

Supply the original pinned source file; the loader verifies its SHA-256, Git blob
and exact byte count before accepting it. From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=qa/stem-bakeoff \
  python -m unittest discover -s qa/stem-bakeoff -p test_memory_retrieval_probe.py -v

python qa/stem-bakeoff/memory_retrieval_probe.py \
  --source /path/to/pinned/locomo10.json --output /tmp/new-locomo-memory-run

python qa/stem-bakeoff/audit_memory_retrieval.py \
  --source /path/to/pinned/locomo10.json \
  --directory qa/stem-bakeoff/evidence/20261022-locomo-memory-retrieval \
  --output /tmp/new-locomo-audit.json
```

Output paths must be new. Retrieval ranks and support scores are deterministic
for the recorded Python/SQLite build; elapsed times and wall-clock receipts vary.
The retained data are original observations, not a placeholder success schema.
