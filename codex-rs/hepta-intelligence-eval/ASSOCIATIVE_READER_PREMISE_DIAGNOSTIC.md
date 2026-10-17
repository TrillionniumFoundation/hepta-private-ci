# Hepta MemoryCell — Privileged Reader Premise Diagnostic (Research Only)

This additive experiment is attached to [PR #2365](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2365), inheriting the prior frozen full-source ranking and selected 20 questions. It does not install a model, alter `cognitive.store/read`, allow production memory activation, certify citations, or issue model-selection authority.

## Why this is necessary

The 240-question frozen ranker evaluated source-ID retrieval, *not* whether the frozen Reader could use sufficient evidence. Before this experiment, the twenty hashed, fixed Reader questions contained complete annotated evidence in **8/20 BM25** and **7/20 RRF** delivered Top-8 sets; the learned question-conditioned Cell found complete evidence in **0/20**. Those are source-ID conditions, not independent semantic sufficiency verdicts.

The follow-on experiment explicitly separates retrieval failure from Reader capacity by adding two **privileged** inputs for precisely the same 20 Reader questions, keeping the same frozen SmolLM2 model, system prompt and 48-token deterministic generation budget:

- `annotated_all`: pass all originally annotated source IDs when every source still exists; otherwise mark unavailable, never substitute another source.
- `annotated_minus_one`: remove exactly one of those sources using a SHA256-bound, question/source-ID-only selection. For single-source questions this is an empty evidence set. It does *not* prove that the removed source is semantically necessary, since alternate evidence and redundant premises can exist.

Neither is a deployment-eligible retrieval policy. Source IDs were selected from the held-out benchmark annotations **after** the earlier candidate ranking was sealed. The `annotated_all` arm does not independently authenticate sufficient evidence; it only checks whether the Reader can use the dataset's claimed evidence. The `annotated_minus_one` arm is an ablation diagnostic, not an exact theorem about information necessity.

## Frozen identities and failure semantics

- Original LoCoMo JSON SHA-256: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Full-source public JSON SHA-256: `e3c9fe407afcc08a153eeb0122b107314443335cb8f153b6557693bdbf900455`.
- Sealed ranking journal SHA-256: `0683fa983bebba19a21a9d4cf2b3064120c3be243a10c88eb45fe3e7635541f6`.
- Source-reader identity: `afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.
- Original ranking run: `38851466159` at head `6b03cb8ca147a9196296522400d49057b15e32bc`. Original inputs stage: run `37862780268`.

A local reconstruction of the fixed published public/rank artifacts identified **19/20** selected questions with every annotated source ID present, and **1/20** question with missing source IDs. The plan therefore has **40 planned condition attempts**, including the unavailable pair. It contains selected source excerpts and source IDs, but no answer string or separate hidden label file. A clean, isolated Reader job may only access that two-file plan and pinned Reader weights. The independent reviewing job reconstructs original reference bytes and checks every source ID, plan and output digest before using answers.

This independent *process* is not an independent evaluator or human sufficiency annotation. Reader outputs are sealed without rewriting answers or fabricating citations. Scoring distinguishes unsupported source conditions, model failures, successful language generations with/without scoreable string references, and the number of fully paired scoreable comparisons. Nonstring/missing reference answers remain unscored rather than assumed false.

## How to reproduce

On a machine with the previously staged, **unchanged** full-source public/rank artifacts and pinned LoCoMo original:

```sh
export PYTHONPATH=scripts/memory_cell
python -m unittest discover -s scripts/memory_cell -p 'test_associative_reader_premise.py' -v
python scripts/memory_cell/associative_reader_premise.py \
  plan /path/trusted-prepared /path/sealed-rank /tmp/premise-plan
python scripts/memory_cell/associative_reader_premise.py \
  reader /tmp/premise-plan /path/pinned-reader /tmp/premise-read
python scripts/memory_cell/associative_reader_premise.py \
  review /path/trusted-prepared /path/public /path/sealed-rank \
    /tmp/premise-plan /tmp/premise-read /tmp/premise-review.json
```

Use output paths that do not already exist; each operation is append-never/create-exclusive. Hosted read-only workflow: `.github/workflows/hepta-associative-reader-premise-diagnostic.yml`.

## Admission and non-claims

This is not a registered production protocol. It does **not** train MemoryCells or change the original 7-arm ranking outcomes. Valid outputs report diagnostic token-F1 (not semantic adjudication), paired comparisons only where both outputs and reference answers are scoreable, original source count 10 (not >=200 independently authenticated source families), `semantic_sufficiency_certified=false`, `statistically_significant_superiority=false`, and `production_accepted=false`.

Continue only after the frozen historical Reader run produces real answer receipts. If the fully annotated arm fails too, prioritize Reader task capacity, formatting, and evidence representation. If it succeeds while RRF fails, prioritize ranking/selection and source set assembly. The strong cached RAG+Reader control, real future windows, signed independent evaluation, corrections, negative transfer and full memory lifecycle gates remain open.
