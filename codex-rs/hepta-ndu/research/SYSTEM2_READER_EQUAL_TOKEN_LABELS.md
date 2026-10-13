# Frozen Qwen: token-length-matched source-label lexical placebo

This is a development-only follow-up on PR #1546. It neither modifies Hepta's
production Reader/Encoder/Cell/NDU/FBSDE/Riccati implementation nor trains,
selects, distills or updates the shared pretrained model.

## Actual completed evidence motivating the test

The completed original run [38338426544](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38338426544), from source commit `56968236c1281908674101568b229c6a1c03359d`, ran **180/180** frozen Qwen2.5-0.5B-Instruct calls without runtime failures, with 1,405 tests passed and 50 skipped, and scoped Ruff passing. GitHub artifact **11787041990** externally SHA256-pinned `8da46b3965f8a6aa9919877c8165e6a2d06f3298921e645d91f7cddfcf9b8761` has 19 individually verified internal manifest files and a sealed 180-row raw answer SHA256 `26736efaedab0f49197011b76190e29dfd241fccfb08d1257c259c9b9b7f5e7f`.

On 20 synthetic TAG-credential questions, only removing `label:E1/E2` from nested JSON increased exact answer yield with target+competing fact from **0/20 to 19/20** (target first) and **1/20 to 20/20** (target last). Single-fact remained 20/20. The removal reduced prompt input length by **ten tokens on each two-source question**. Critically, when the target fact was missing, **both variants copied an unsupported TAG code in 20/20 attempts**, and an empty evidence list yielded only 19/20 exact refusals. The registered primary comprehensive acceptance gate **failed**, correctly producing `tag_label_selection_not_qualified`. These are 20 correlated generated tasks; they do not establish production-grade refusal, causal label semantics, general NDU/FBSDE improvement or independent domain competence.

## New fixed, testable hypothesis

The original effect mixes two changes: the literal `E1/E2` label values and removal of the entire JSON `label` field with a shorter tokenized input. This experiment compares a label-value-only control at **identical per-question input token length**, alongside the original no-field treatment.

Create **20 previously untested-by-this-protocol synthetic question IDs at the fixed generator indices 100:120**, disjoint from the preceding 80:100 slice. For each question, exactly three source selectors with identical underlying source bytes are registered:

1. Target fact followed by competing TAG fact.
2. The **same two source documents reversed**, target fact last.
3. Only an unrelated TAG fact (no target relation), to measure unsupported copying and refusal.

For each selected source set, keep the **same question, system instruction, source text, observed time, original source IDs, model weights/revision, greedy-64 decoder, and JSON field order**. Compare three input presentations:

- `e_label`: original `label:"E1"/"E2"`.
- `neutral_alias`: same `label` property and source field placement, but labels `A1/A2`, `B1/B2`, etc., chosen from a **fixed public candidate list** purely by the frozen tokenizer to require **exactly the same total prompt token count** as the E-label condition. Use the first fitting letter deterministically; no answer, label or model prediction is considered.
- `unlabeled`: remove the `label` property entirely, preserving all source texts and source-ID provenance.

Each question also gets one empty-evidence `unlabeled` control. The declared **200 total new frozen-model calls** are `20 × (3 × 3 + 1)`. Never treat 200 calls as 200 independent questions. Actual input/output token counts and decoder CPU time are recorded for every attempt.

### Execution ordering and failure boundaries

Before the first neural call, the script verifies the same pinned Qwen original 160-answer source ZIP, the Qwen model snapshot inventory, all new source selection identities, and executes the **entire per-question tokenizer preflight**. A neutral alias *must* be found with **exact per-question input token count parity**. If none exists, fail **before** the first model inference and preserve the failure receipt; don't quietly relax the token-length constraint, change questions or count absent work as free. Preflight source/input fingerprints are fsynced and SHA-sealed before any model calls. All answer starts and raw model results are journaled, then the raw answer file is sealed **before** synthetic grading. Independent final source validation still applies. No evidence is shortened or retrieved from a different task.

The primary readout is a paired answer/copy/refusal table for all 20 question IDs, by source condition. It reports exact target output, correct refusal, unsupported copy, label-list echo, and actual input/output token/CPU counters separately. Require **at least 15/20 exact answers in EACH supported neutral-alias arm** and **18/20 correct refusals in BOTH insufficient neutral-alias and empty-evidence arms** to justify a later independent natural-task confirmation; **never** production. Original E-label versus matched neutral alias has exactly equal *input sequence length* by construction, **not** identical token identities, causal label-semantics isolation, or equal total decoder compute. The no-label contrast is explicitly shorter.

We do not infer that the external proof parser or the system's generated refusal/citation was learned by Qwen. General language/multimodal reasoning ability, calibrated NDU continuation, and 10T/100T Cell equivalence are NOT established here.

## Reproduce from exact checkout

```
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_reader_equal_token_labels.py \
  /path/to/externally-pinned-qwen-original-160.zip \
  /path/to/exact-qwen-0.5b-snapshot \
  /new/equal-label-trial --development
```

The isolated hosted GitHub Actions workflow installs pinned dependencies, runs the entire MemoryCell regression and scoped Ruff checks, re-verifies the original source and exact checkpoint inventory, executes the preflight and inference trial, and uploads environment/source hashes, input and output seals and all raw attempts. No blocking CI check is bypassed; this PR remains draft and separate from serving.
