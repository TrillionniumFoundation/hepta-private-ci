# Frozen 0.5B Reader: identical evidence, JSON versus line records

This is an opt-in, standalone diagnostic on draft PR #1546, not a production
Reader substitution or a Cell/NDU/FBSDE gain. The completed externally pinned
Qwen2.5-0.5B-Instruct experiment (artifact `11768355664`, outer SHA256
`853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37`)
had **zero exact answer-only outputs** in its eighty fully evidenced question
conditions. It refused all eighty insufficient-evidence conditions exactly,
but **also refused the supported ones**. A 0.5B Reader is therefore not
adequate under that JSON representation and unchanged SYSTEM instruction,
despite better refusal than the historical 135M Reader. This is an
**over-refusal pattern**, not a general language model comparison: the
original 135M and 0.5B models have different tokenizers and CPU/FLOPs.

## Controlled next question

Can the **same exact Qwen2.5-0.5B checkpoint**, frozen SYSTEM, decoded token
ceiling and original evidence, produce supported answers when source excerpts
are rendered as readable line records rather than as nested JSON?

The *only* new online change is user-message serialization. The unchanged
SYSTEM is imported from `system2_onehop_label_ablation.SYSTEM`, each original
excerpt stays byte-for-byte complete and JSON-quoted for data/instruction
separation, original source order and E labels remain, and the frozen greedy
64-token decoder is unchanged. The old nested JSON uses the exact original
`prompt_messages` function; no new answer, gold label or oracle enters either
prompt. Real input/output tokens and model CPU time are recorded independently
and are **not matched**. No answer or citation is rewritten after generation.

## Registered cohorts, actions, workload

The four unchanged arms are: exact one-fact support, the same device fact plus
one competing Token fact, one unrelated Token fact, and no evidence. Cohort
identities are the registered hash-ordered original 20, fixed next 20 (both
used in the original pinned 0.5B study), and **index positions 40:60** of the
same generated arithmetic-like English device/token family, fixed in source
before any new Reader calls. This third cohort is *new to this particular
study* but not an independent natural-language or human-judged domain.

- Original forty questions × four arms: reuse all **160 original JSON
  responses** (zero redundant model calls) and generate 160 new line-record
  answers.
- Additional fixed twenty questions × four arms: generate *both* JSON and
  line-record outputs (160 new answers).
- **320 new frozen-Reader calls**, 160 archived controls, and 240 registered
  question-arm pairs in total. Model training updates remain zero.

Before loading or running the model: verify the 160-answer archive's external
SHA, every internal SHA256SUMS entry, source commit/tree, raw response seal,
original Qwen model inventory and revision. After loading the exact same model
snapshot, retokenize ALL 160 old JSON prompts and require matching input token
IDs digest, input-token count, model, question and source/bundle identities,
selected original source bytes, original source order and frozen profile. A
mismatch aborts without a model call. The new 20 have paired simultaneous
JSON/line outputs; both are scored only after all raw answers are sealed.

Report **answer yield** (exact correct TOK), **appropriate refusal** and
**over-refusal on sufficiently evidenced cases** separately, plus label echoes,
unsupported target copies, token/CPU costs and all planned denominators.
All failed or interrupted calls retain start journals and unknown work, and a
failure invalidates any success claim.

Primary qualification on the fixed additional twenty questions requires:
- **at least 15/20 exact supported answers** under line records, in BOTH
  supported arms;
- **at least 18/20 prescribed refusals** in BOTH insufficient
  evidence arms;
- no new-question condition with a paired JSON success that
  becomes a line-record failure.

These criteria merely permit a further independent confirmation. They are
*not* proof of calibrated NDU, general reasoning emergence, semantically
adequate quotations or independent natural-language transfer.

## Reproduce

On the exact checkout, after setting `HEPTA_MEMORY_TESTED_COMMIT` to its Git
commit ID and downloading/staging the pinned model snapshot and parent ZIP:

```
python scripts/memory_cell/system2_reader_transport_trial.py \
  /path/to/strong-0p5b-parent.zip /path/to/exact-pinned-model \
  /new/transport-output --development
```

The isolated workflow installs the repo-pinned CPU PyTorch environment, runs
ALL existing MemoryCell tests and scoped Ruff, compares the model inventory
against the original GitHub artifact, invokes the frozen Reader and uploads
complete raw/model/plan/CPU/source receipts and SHA256 manifests. Default
Reader, Encoder, production search, data owners and native NDU/Riccati/FBSDE
backend are unchanged. A completed hosted run is mandatory before any new
neural performance assertion.
