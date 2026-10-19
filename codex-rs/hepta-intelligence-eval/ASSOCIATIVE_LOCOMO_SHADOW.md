# LoCoMo dialogue-family associative MemoryCell shadow — research only

This addition belongs to the existing **learning.eval** experiment lane on the stacked
MemoryCell PR. It **does not** create a production writer/reader, issue authority, promote
any learned adapter, claim general associative memory, or waive `blocking-ci`.

## Frozen input and exact execution contract

Input: the pre-staged `memory-inputs/locomo.json` from the existing
`memory-native-staged-inputs` research artifact (original source run `37862780268`).
The admitted local JSON SHA256 is:

`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`

There are **10 distinct LoCoMo authored dialogue groups**, not 10 externally authenticated
independent families. Questions and conversations come from the published benchmark;
source/authorship/training-consent independence is not established by dataset IDs.
The encoder is exactly the six-file all-MiniLM-L6-v2 snapshot already used by the
preceding offline probe, identity
`5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a`.
The custom CPU implementation must pass separate Hugging Face tokenizer/vector parity;
its inventory match is **not** functional parity evidence.

This experiment preregisters the following deterministic corpus and workload:

- Dialogue source pool: **first 128 eligible source turns per group**, in original session order, independent of answer or supporting-evidence labels. Eligible turns are printable ASCII within byte and tokenizer bounds. Zero truncation allowed. Any later source turn remains unavailable to every compared arm.
- Question sample: **24 per group**, selected by a stable hash over the original question ID only, *not* by answer, category or evidence. The 240 question texts are available during inference; targets are not.
- Fixed source-only training: each source turn is encoded as speaker + utterance cue; its own utterance encoding is the value target. This is **auto-association**. It is not direct training of question→answer memory, and should not be presented as such.
- Shared encoder and projection: frozen MiniLM plus seeded deterministic 384→64 projection. Each dialogue has a local rank-8 MemoryCell (1,024 trainable scalars). Candidate split yields two rank-4 child Cells (combined 1,024 parameters). The type labels are a visible **keyword heuristic**, not discovered semantic/procedural expertise.
- Parent runs 128 self-supervision updates. Parent continuation takes 64 further updates; each of two children takes 64. This matches aggregate trainable-parameter touches for the continuation, **not** training example counts, actual FLOPs or wall-time. Both model selection and factual permissions stay elsewhere.
- Eight fixed source-ranking arms: frozen parent; trained parent; continued shared; type split; swapped type-route ablation; cached dense cosine; cached lexical BM25; fixed RRF fusion. The parameter arms need an **external original source-value vector catalogue** to decode their latent output back into candidate source IDs. They are **not** parameter-only natural-language readers. All arms return top-8 IDs from the same 128-source pool.

`prepare` is the trusted benchmark import boundary that reads source plus labels and
writes `public.json`, `private.json` and a hashed manifest. For actual generation,
copy **only `public.json` and `manifest.json`** into a separate inference directory;
the `run` command rejects the presence of `private.json`. It runs only on public
source/question text and the frozen Encoder. It creates `journal.json` and
`seal.json` with canonical byte SHA256 before `review` is invoked. Only then does
the reviewer open the private annotation file. A local digest seal is **not an
independent signature or unforgeable source authentication**.

## Reproduce without a GitHub Actions queue

From the repository root, with pinned CPU PyTorch, NumPy and safetensors available
and the original staged dataset and six encoder files materialized:

```bash
export PYTHONPATH=scripts/memory_cell
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_associative_locomo_shadow.py' -v
python3 scripts/memory_cell/associative_locomo_shadow.py prepare \
  /path/to/memory-inputs/locomo.json /tmp/locomo-prepared
mkdir -p /tmp/locomo-public
cp /tmp/locomo-prepared/public.json /tmp/locomo-prepared/manifest.json \
  /tmp/locomo-public/
python3 scripts/memory_cell/associative_locomo_shadow.py run \
  /tmp/locomo-public /path/to/pinned/encoder /tmp/locomo-run
python3 scripts/memory_cell/associative_locomo_shadow.py review \
  /tmp/locomo-prepared /tmp/locomo-run /tmp/locomo-review.json
python3 scripts/memory_cell/associative_locomo_shadow.py frontier \
  /path/to/memory-inputs/locomo.json /tmp/locomo-prepared \
  /tmp/locomo-run /tmp/locomo-post-seal-frontier.json
```

Each destination must not exist. Raw source text, benchmark answer annotations,
pretrained weights and sensitive samples should not be committed in the PR.
The read-only CI recipe lives at
`.github/workflows/hepta-associative-locomo-shadow.yml`, and requires pinned
Hugging Face parity before any hosted shadow attempt. A queued or skipped workflow
is not a completed execution receipt.

## Actual local results from the pinned, source-only sample

An initial local run executed **240/240 predictions** on the actual staged MiniLM
CPU weights; model execution wall time was about 36 seconds on the available host.
The independent original Transformers parity gate was **not** available locally.
All metrics below are source-ID retrieval diagnostics, not answer accuracy, not
semantic citation precision, not independent task benefit.

| Predeclared arm | Any reference at top-8 across 238 referenced Q | All references at top-8 for 38 pool-eligible Q |
| --- | ---: | ---: |
| Frozen untrained parent | 6/238 | 2/38 |
| Parent trained | 7/238 | 3/38 |
| Continued shared | 6/238 | 2/38 |
| Type split (correct heuristic route) | 7/238 | 3/38 |
| Type split (swapped route) | 6/238 | 2/38 |
| Dense cosine | 30/238 | 21/38 |
| Cached BM25 | 31/238 | 22/38 |
| Cached RRF (dense + BM25) | **34/238** | **24/38** |

Only **38/240** questions have all ground-truth evidence IDs in the first-128
source pool; 57/240 have at least one available gold source, 2/240 have malformed
or unresolved published reference strings and are excluded from referenced-Q
rates. These are benchmark evidence labels, **not** separately adjudicated
semantic entailment. No row-wise independent-sample confidence interval is valid;
the actual independent experiment count is far below qualification thresholds.

### Post-seal information-availability frontier

After the 240-prediction journal was sealed, a separate, explicitly **post hoc**
source-only diagnostic checked the *availability ceiling*, without re-running
or selecting any model, at progressively longer prefixes:

| Source turns per dialogue | Questions with *all* labelled sources present |
| ---: | ---: |
| 32 | 15/238 |
| 64 | 21/238 |
| **128 (tested)** | **38/238** |
| 256 | 84/238 |
| 512 | 176/238 |
| All ASCII-eligible source turns | 224/238 |

These are **not** retrieval or model performance scores at the longer limits.
The large source-availability gap is a concrete reason to prioritize better
bounded full-source retrieval and Reader sufficiency checks before enlarging
the Cell topology. Retuning any policy against these post-seal values must use
fresh source-family and calendar holdouts, not relabel this trial as prospective.

## Hard remaining blockers

- **MiniLM parity** with the original Transformers tokenizer/embedding vectors on a verified exact runtime remains required. The local source/weight hashes cannot substitute.
- **End-to-end Reader** with sufficient-source, removed-premise and insufficient-source negative controls has not executed here. BM25/Dense/RRF are fixed research baselines, **not** a strong tuned RAG system.
- **Parametric memory vs. RAG advantage is negative** on this evaluated ranking task; type route results are too weak to support learned type specialization.
- **True independent source-family generalization**, real future calendar windows, three independent authenticated snapshots, source withdrawal/unlearning, independent semantic evaluation, calibrated uncertainty, full cost, and promotion/rollback remain absent.
- All new artifacts have `production_accepted=false` and `superiority_claim=false`. No `main` merge, permission widening or serving activation is authorized by a diagnostic run.
