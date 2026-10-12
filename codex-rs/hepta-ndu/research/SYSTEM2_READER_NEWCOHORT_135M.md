# Fixed-new-20 same-question 135M Reader: the missing capacity comparator

Research-only, one additional controlled experiment on the **same existing draft
PR #1546**. The 0.5B Qwen reference in `system2_reader_capacity_reference.py`
proposes 160 answers across the exposed 20 questions and positions 20:40 of
this deterministic synthetic corpus. Previously, the original frozen 135M
model had completed only the **old** 20 question identities with the answer-only
system prompt. Comparing Qwen's newly generated 20 questions with 135M's
already-exposed old 20 would confound model choice with question difficulty.
This experiment supplies precisely the missing **80 original 135M calls** for
those same new20 tasks (20 questions x 4 fixed evidence arms), so both Readers
can eventually be compared on the same 40 question IDs and source excerpts.
It is NOT an NDU/FBSDE improvement or a new natural-language benchmark.

## Before generation: exact original request parity

Externally pin both previously completed hosted original-Reader ZIPs:

- original cardinality 140: artifact `11756357532`, SHA256
  `9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121`;
- E-coded/unlabeled 140: artifact `11760345185`, SHA256
  `a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a`.

`load_baseline_archives` checks their external and internal member hashes,
complete old-result census, model/source receipts, raw-seal and original scores.
The exact historic 135M Reader files come from immutable staged artifact
`11586991191` (outer SHA256
`07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`),
with `stem_cell_trial.READER` file inventory pin.

**No original model inference is repeated.** Before starting the new 80 calls,
re-tokenize all *80 old* labeled or empty-unlabeled original prompts using the
restored, frozen 135M checkpoint. Require exact equality of the 80 earlier
`input_ids_digest`, `input_tokens`, `reader_profile`, question identity,
original evidence IDs/excerpt bytes and source bundle identity. If any value
changes (model, tokenizer, prompt, question, code or old source), abort **before
loading new evaluation questions into inference**. Only completed old rows are
reused; they are not counted as new model calls or independently generated
questions.

## Protocol fixed without viewing larger-Reader outputs

- Question cohort: exactly positions **20:40** as defined by
  `system2_reader_capacity_reference.fixed_new_cases()`; one disjoint numeric
  multiset family, same synthetic question/answer template as original 20.
- Identical four arms as 0.5B: `single_fact`,
  `target_decoy_two_first`, `decoy_one`, `no_evidence`. All fact selectors use
  question and original source bytes; the expected answer is never supplied.
- **Identical exact system/user message strings** as the 0.5B comparator, by
  importing the common `prompt_messages` function with original `E1/E2` labels
  except no-evidence prompts which have no labels. Same max input token count
  1024, greedy decoder max 64 new tokens, 0 trainable parameters.
- **Not equal inference cost:** the 0.5B checkpoint, 135M checkpoint and their
  tokenizers differ. Record real input/output tokens, CPU/wall and returned
  answer hashes. The new CPU interval includes prompt preparation as well as
  model inference; it is **not** presented as directly equivalent to the
  0.5B generator-only CPU interval. Future comparisons must state model and
  cost differences explicitly.
- Reuse the old 80 answers once, generate exactly 80 new, durable-journal each
  start and completed/failed attempt, seal all NEW raw responses before scoring
  only their correct answers and strict refusals. Unsupported correct-token
  copying in decoy/no-evidence arms is never success. Failed or in-flight work
  remains UNKNOWN, not a zero-cost negative.

## Admission and interpretation

A green result proves that a **fixed, exact** 135M Reader reference exists on
all the same questions as the planned stronger reference. It does **not** by
itself establish any 0.5B advantage, CPU equivalence, independent-language
accuracy, calibrated NDU continuation, or production feasibility. If the larger
run fails, its missing outcomes remain unknown and this 135M cohort is kept as
research evidence; no simulated or post-hoc Qwen answers are invented.

On source-slice Python 3.13 / CPU environment, 20 targeted tests passed,
including a complete 80-position fake-model trial, exact original archive
hash/score validation, tokenized old-request parity, unsupported-copy scoring,
fail-closed model/source tampering and durable failure receipts. Fake-model
answers are **only unit tests** and are never cited as neural evidence. Hosted
full-repository pinned Torch 2.5.1 regression and Ruff checks remain separate
mandatory gates. No main merge, model training, owner write, Encoder change or
production switch is authorized.

`production_accepted=false`, `new_model_capacity_gain_unproven=true`,
`stronger_reference_not_compute_matched=true`,
`independent_natural_task_transfer=false`.

Reproduce after the three source archives are pinned and extracted:

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
python scripts/memory_cell/system2_reader_newcohort_135m.py \
  /tmp/onehop-cardinality-140.zip /tmp/onehop-label-140.zip \
  /tmp/memory-inputs/reader /new/reader-newcohort-135m --development
```
