# Hepta MemoryCell — question-conditioned, full-source LoCoMo shadow

**Research-only; no production candidate, learning selection, rollout, fact/effect
owner, authority grant or new Memory OS.** This lab is stacked on PR #2365 and
uses existing `neuron.runtime`, `learning.eval`, `cognitive.read`, `learning.artifacts`
and source-lineage boundaries. Its producer is a fixed, read-only evaluation
runner, not a deployed training or serving component.

## Motivation and frozen scope

The earlier 128/256-source LoCoMo experiments yielded poor parametric evidence
coverage while source availability increased strongly with pool size. This next
step separates two problems:

1. **Source coverage:** expose all bounded, eligible original dialogue messages
   to cached BM25+dense retrieval instead of a prefix of 128/256.
2. **Question conditioning:** change only the *training cue* for a tiny
   associative Cell from source echo to a deterministic, source-derived,
   question-shaped cue. Its value target remains the same original source
   embedding. No human question, answer, reference evidence or reviewer feedback
   enters training or model selection.

The indexed retrieval arms retain the **whole** source pool and value vectors.
The parameter-only map emits a 64-dim vector, but the experimental ranking
**uses an external source-value catalogue** to turn that vector into source IDs.
Neither is parameter-only language recall; both incur storage and inference
costs for that catalogue. Do not rename this as an answer-generating memory.

Dataset: published LoCoMo `locomo.json` SHA-256
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`;
10 authored dialogue families, 240 preselected questions. Frozen shared Encoder:
all-MiniLM-L6-v2 registered exact inventory
`5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a`.
Readout: deterministic 384→64 JL projection (seed 2718) and fixed model.

## Study arms and costs

Seven arms consume exactly the same visible question and source candidate pool:

| Arm | Training / data use | Ranking |
|---|---|---|
| `frozen` | untrained 1,024-parameter Cell | Parametric vector + source catalogue |
| `auto_association` | 128 source-only SGD steps | Source-echo associative Cell |
| `question_conditioned` | 128 source-only SGD steps | Keyword-question associative Cell |
| `dense` | none | Dense cosine over cached original source encodings |
| `bm25` | none | Cached lexical BM25 from the same sources |
| `rrf` | none | Fixed rank-fusion (constant 60) |
| `rrf_question_conditioned` | same Q-Cell and source store | Fixed RRF + `0.25/(60+qrank)` |

Both trained Cell arms share seed, frozen Encoder, rank-8 architecture,
64-dimensional readout, 1,024 float32 parameters, exactly 128 SGD steps,
learning rate 0.25, and the FIRST 128 source records in each family. They differ
only in the input cue representation. No held-out question template or answer
is used to optimize the pseudo-question cue. The registered source-only prompt
is `What did <speaker> say about <first five allowed content keywords>?`.
This is **weak generated supervision**, not a language-question teacher.

Complete lifecycle cost is **not** equalized: BM25/dense retain source vectors,
and the parametric arms also need the source catalogue to rank documents. Shared
Encoder weights (90+ MB), source bytes, per-query encoding, tensor artifacts,
index construction, ranking, replay and Reader cost must all be reported; do
not use the 4,096-byte Cell tensor alone as a compression ratio. Observed local
wall times include batch encoding and training, but are not token-level matched
end-to-end serving costs. Read-only CI reports OS resource consumption.

## Trust and blinded evaluation

1. `prepare` opens only an exact-pinned original benchmark and verifies that
   its first 256 eligible sources and 240 question IDs exactly match the
   previously fixed no-label input rule. It produces `public.json`, private
   `private.json` and `manifest.json` with hashes; only this trusted step may
   read the answer and evidence annotations.
2. A physically isolated `public` directory contains **only** `public.json`
   and `manifest.json`. Unknown question/source fields, hidden reference files,
   source identity or scope drift, duplicate keys, extra arms, invalid candidate
   IDs, wrong counts and unsealed mutations fail closed.
3. `run` executes all 240 questions on the current source pool. It exports
   low-rank model parameters and source-root lineage, but not the training
   samples, reference answers, raw query text or retained source vectors.
   It hash-seals the exact 7-arm prediction journal before review.
4. `review` only then accesses the private reference file and scores ID-level
   complete evidence coverage, any-hit and first-hit, with one dialogue as
   the effective cluster. No independent semantic entailment is conferred.
5. The **separate** `frozen-reader` GitHub job downloads the label-free public
   source/ranking artifact and frozen SmolLM2-135M-Instruct checkpoint. It has
   no private reference file. Two question IDs per dialogue are selected by a
   fixed hash before seeing any answers. All five Reader arms have the same
   model, prompt semantics, evidence excerpt policy, decoding budget and
   token ceiling: empty, BM25, RRF, parameter Cell, and RRF+Cell.
6. A third job independently reconstructs the frozen private reference from
   the exact same original benchmark, verifies public byte-for-byte parity,
   and scores the **already sealed** Reader output with diagnostic token-F1.
   The source-reference labels are not independent semantic citation verdicts.

Reader checkpoint inventory identity:
`afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.
The Reader is always frozen and uses deterministic decoding (`max_new_tokens=48`,
`do_sample=false`, `num_beams=1`). The 48-token budget is a **new versioned
experiment profile**, not an identity-preserving replay of the historical
64-token benchmark Reader. Per-arm generation failures and over-budget prompts
stay in the denominator; they never become automatic zeros silently.

## Observed local CPU result (2026-10-16; research only)

The newly executed full-source 7-arm experiment used actual registered MiniLM
weights, 5,804 ASCII-admitted messages, 10 dialogue families, 240 questions,
128 source-only training updates per Cell arm and all-source recall. Reference
labels were opened after the model journal was complete and SHA-256 sealed.
There are **238 positive, canonical-evidence questions**; 2 published reference
records have unresolved evidence identities. 224/238 positives have every
annotated reference inside the full admitted source pool.

| Arm | Complete Top-8 evidence, among 238 valid references |
|---|---:|
| frozen | 2 |
| auto association | 4 |
| question conditioned | **1** |
| dense | 62 |
| BM25 | **107** |
| RRF | 100 |
| RRF + question Cell | 101 |

The question-conditioned weak trainer **does not work better** than the echo
trainer here. In this exploratory study even fixed `RRF+QCell` wins only one
case over the frozen RRF count and cannot be promoted on that basis. The
all-source BM25 control is strictly stronger on this task/readout measure.
These are **not** semantic answer scores, not an optimized strong RAG+Reader,
not an independent prospective split, not 200 independent families and not
an accepted causal topology benefit. The separate frozen Reader execution is
specified by CI and is **not a local result**. A successful workflow must be
checked at the exact commit before any Reader result can be claimed.

## Reproduction

With PyTorch/safetensors and the exact staged source+Encoder files, from repo
root (outputs must not preexist):

```bash
export PYTHONPATH=scripts/memory_cell
export HEPTA_ASSOC_LOCOMO_FILE=/path/to/pinned/locomo.json
python -m unittest discover -s scripts/memory_cell \
  -p 'test_associative_question_conditioned.py' -v
python scripts/memory_cell/associative_question_conditioned.py prepare \
  "$HEPTA_ASSOC_LOCOMO_FILE" /tmp/qc-prepared
mkdir /tmp/qc-public
cp /tmp/qc-prepared/{public,manifest}.json /tmp/qc-public/
python scripts/memory_cell/associative_question_conditioned.py run \
  /tmp/qc-public /path/to/pinned/encoder /tmp/qc-run
python scripts/memory_cell/associative_question_conditioned.py review \
  /tmp/qc-prepared /tmp/qc-run /tmp/qc-review.json
```

The optional `reader` and `review-reader` subcommands need the actual pinned
Transformers/PEFT/SmolLM2 environment; see
`.github/workflows/hepta-associative-question-conditioned-fullsource.yml` for
**separate workers** and exact commands. Local Python lacking Transformers
cannot be described as a completed semantic Reader run.

## Admission status and blockers

- **Research-only; production_accepted=false, superiority=false.**
- No signed independent semantic correctness or citation-entailment census.
- No authenticated >=200 independent source-family samples or two real future
  calendar windows. Ten LoCoMo conversations are ten correlated groups.
- No causal graph / cell split / automatic meta-network superiority.
- The pseudo-question input is still too far from authentic user questions;
  training loss improvement is not task utility and this negative result must
  remain visible.
- Strong cached hybrid+graph+temporal RAG, real Reader completion, source
  corrections, withdrawal/erasure proofs, Reader capacity controls and lifecycle
  storage/latency parity are outstanding.
- Existing current owner, authority, artifact lineage, outbox and withdrawal
  constraints are unchanged. Do not waive blocking CI or claim release.
