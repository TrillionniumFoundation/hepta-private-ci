# MemoryCell four-stage evidence: original-byte audit

This is a research-only extension to the existing
`factorial_evidence_gate.py`, not a new memory backend or serving owner.
The objective is to falsify confounded gains **before** training or promotion.
It does not generate model responses, rewrite answers or authorize deployment.

## Stage order

1. **Reader solvability:** Fix development questions, project/source families,
   two immutable and distinct reader revisions, system/prompt template, output
   token ceiling, tool permissions and four conditions `none`, `hybrid`,
   `oracle` and `ablated`. The reference tier diagnoses capacity; it is
   **not** counted as a MemoryCell gain. After generation, separately review
   whether the oracle context was genuinely sufficient and whether removing
   the declared premise actually removed the necessary information. Byte
   deletion is not proof of semantic necessity.
2. **Nonparametric organization:** Compare ordinary strong hybrid RAG against
   event-level segmentation, entity/time projection, conflict resolution and
   evidence-set completion, with the same frozen reader and tool permission
   envelope. Record actual task execution, diagnosis iterations and recovery.
3. **Parameter module:** Write experiences and freeze module/artifact revisions
   **before** exposing future cases. With matched delivered evidence, compare
   the organized graph to a learned reading policy and experience-knowledge
   adapter separately. `knowledge_only` receives **no original evidence**
   under any condition; its performance does not replace a strong RAG baseline.
4. **Lifecycle:** Independently admit new source families and two actual future
   collection windows. Account for extraction, indexing, training, inference,
   tools, source storage, maintenance, revocation and recovery. Unknown cost
   fields stay unknown rather than zero; do not infer recovery from a unit test.

The inherited eight authored diagnostic questions and archived benchmark
replays are *exposed development data*, not new independent future tasks.
Synthetic regressions only verify that invalid evidence fails closed.
Semantic citation entailment, independent human review, source authenticity,
program execution, model-call attestation and production qualification remain
separate requirements.

## Exact transcript contract

Inputs are **three** bounded JSON files, given to a read-only verifier:

```bash
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/factorial_transcript_integrity.py \
  --plan /path/frozen-plan.json \
  --observations /path/scored-observations.json \
  --transcripts /path/raw-transcripts.json \
  --output /path/new-audit.json
```

The plan is the existing `hepta.memory-factorial.plan.v1` matrix of five arms,
two readers, four evidence conditions and all four tasks (`new_fact`,
`update`, `cross_experience`, `program`). It must be frozen before task
exposure. For this strict byte-level profile, **each case additionally has**:

- `question_sha256`: SHA-256 of the unmodified UTF-8 question.
- `admitted_evidence`: array of `{"id":"source-id","sha256":"hex64"}`,
  with SHA-256 computed over each original UTF-8 evidence body.
- `oracle_source_sha256`: `sha()` of the ordered oracle evidence array
  `[{"id":"source-id","text":"original complete body"}, ...]` using
  the existing canonical JSON encoding (`sort_keys=True`, compact
  separators, UTF-8, no NaN).
- `premise_sha256`: SHA-256 of the UTF-8 body of exactly **one** oracle
  source that must be removed to form the ablated condition.

Each raw transcript has exactly one `id`/`arm`/`condition`/`reader`
combination and records:

```json
{
  "id": "case-1",
  "arm": "hybrid_rag",
  "condition": "oracle",
  "reader": "frozen",
  "question": "The originally registered question",
  "delivered_evidence": [{"id": "s1", "text": "The original evidence body"}],
  "raw_answer": "The original, unedited model output",
  "prompt_template": "The exact frozen template, excluding condition evidence",
  "reader_revision": "immutable-pinned-model-revision"
}
```

Each scored observation must carry the SHA-256 of its raw answer bytes
(`answer_digest`), its `sha(delivered_evidence)` (`source_digest`),
the SHA-256 of the prompt-template text (`prompt_digest`), exactly the
same `reader_revision`, and the SHA-256 of the complete frozen plan.
Both reader identities must differ, while each identity remains fixed across
tasks, evidence conditions and arms.

The verifier checks all 40 slots per case (5 arms x 4 conditions x 2 readers)
without dropping failed attempts, rejects duplicate/missing entries or altered
answers, and ensures the oracle evidence bytes are identical across the four
non-parametric-only arms. The ablation must be exactly the oracle list minus the
single preregistered source. A same-hash assertion without original evidence
and answer text is **not** accepted as byte-level provenance.

`knowledge_only` receives no source text even for the named oracle condition;
it is excluded from oracle/lesion equality on purpose. A meaningful learned
module must be separately identified by a frozen artifact and pre-exposure
writer receipts; none of that can be certified from the JSON alone.

## Test and interpretation

```bash
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_factorial*.py' -v
```

The lightweight workflow `hepta-memory-factorial-integrity.yml` records the
tested **exact HEAD**, test output and SHA-256 inventory. It does **not** call
any pretrained reader. To obtain real capability evidence, execute the
separately pinned frozen/reference model runners with genuine recorded inputs,
preserve every raw answer before labels are opened, and transfer these bytes
into this registered transcript profile. Independently adjudicate task success,
source sufficiency, program execution and cost. Do not fabricate empty/no-op
adapter arms to fill a matrix: if a real arm has not been executed, the
complete-factorial claim must remain unavailable.

Positive protocol results only mean that the submitted bytes are internally
consistent with the plan. Even after this check,
`source_authenticity_independently_verified`,
`model_execution_independently_attested`,
`independent_task_success_adjudicated`,
`parameter_learning_qualified` and `production_accepted` remain false.
