# P0 V16 strict staged mmBERT physical rejection — DRAFT / DENY_ALL

**Frozen predecessor:** P0 V15 original-human research parent #2378 at
`b0586cdd8c856a63693542aca92086e73b98d69b`.

## Observed production-independent research blocker

The exact-source physical V15 source+merge jobs in GitHub run **38888885866**
failed at `Execute original strict byte-checked MLM and real CPU forward`,
with only sanitized `exception_class=Invalid`. Original SHA/LFS preflight and
model-free regressions had passed. From that output alone it is not possible
to determine whether the actual rejection was caused by MLM loading metadata,
architecture mismatch, tensor storage alias, actual original saved table bytes,
complete saved tensor bytes, or a real frozen CPU forward.

The prior pinned V14 names-only report was **137 source tensors / 138 runtime
names / 0 missing non-tied keys**. That observation alone is NOT source-byte
integrity or valid model inference and must not be treated as acceptance.

## Additional independent, fail-closed observation

`p0_mmbert_stage_census_v16.py` performs exactly these ordered stages on the
original immutable mmBERT-small `0eb3d056...` checkpoint and original pinned
runtime: source SHA/LFS preflight, pinned source checkout and native runtime imports,
AutoModelForMaskedLM loading, strict V15
alias report, 384D tied ModernBERT architecture, actual physical embedding /
decoder storage alias, **entire original tied-table bytes**, **all serialized
pretrained tensor bytes**, and finally a new frozen inference through the
original `FrozenMMBert` loader and Q24 output path.

Stages call the existing P0 V15 loader and EXACT existing native byte-verifier
functions, not substitute weights or fake features. On the first failure the
script records **only a fixed stage name and exception class**, never exception
message, path, model tensor data, training labels or unbounded stack trace.
It writes the sanitized report create-only, then exits **nonzero**. The source
and prospective merge GitHub jobs are independent; `actions/upload-artifact`
uses `if: always()` so a failure receipt may survive without masking the
failed job. All output retains `DENY_ALL`.

## Qualification scope

Model-free stage and source-custody fault tests run in normal and optimized
Python. The existing original V15 tied-alias loading policy and original
full-source-tensor synthetic tamper tests also execute on pinned CPU Torch.
The actual hosted SHA/LFS revision is unchanged; no `HF_HUB_OFFLINE` silent
fallback, altered tokenizer, truncation, unverified publisher alias or skipped
CPU forward is admitted.

If every stage passes, this STILL proves only the source-bound frozen model
mechanism for this exact research run: it does **not** prove original task
accuracy, complete four-model V5/V6/V7, independent publisher signatures,
future utility, 4096-Cell TCO, NDU decisions, production FinalUse or physical
Cell Split. If any stage fails, it is a hard scientific acceptance blocker.

**DRAFT / RESEARCH ONLY / DENY_ALL. Do not merge main or select a model.**

## V16.1 stage-attribution correction

The original eight-stage stage census had two untracked boundaries: the
pinned source checkout/native Python imports between source preflight and
`original_mlm_load`, and the original safetensors local acquisition before
`original_tied_table_bytes`. A failed import could be falsely labeled as an
MLM load failure, and a missing source file could be labeled as a later gate.

V16.1 adds `runtime_checkout_and_imports` as a separate **ninth** recorded
physical boundary and moves the source-file access into the actual tied-table
validation stage. Cold loader cleanup is recorded with the forward stage, while **releasing**
the first full MLM model before the second cold load to preserve peak-RSS
semantics.
Any exceptional failure outside these explicitly wrapped steps is reported
only as `external_setup` with a bounded exception *class*, never guessed as
the next model/weight gate. No changed model revision, allowed alias, original
weight verification, CPU forward, source or label custody or FinalUse authority.
The run still exits nonzero on failure and always produces `DENY_ALL`.

## V16.2 bounded loading-report container observation

When real Transformers loading metadata is rejected at the **unchanged**
`strict_alias_loading_report` stage, store four fixed field labels with only
the kind (`list`, `tuple`, `set`, `frozenset`, `none`, `absent`, `unsupported`)
and a bounded count when an allowed collection has at most 8,192 names.
No parameter names, prompt content, logits, model files, exception text or
arbitrary type names/reprs are serialized. No iterable from the underlying
library is traversed, and unknown report objects cannot masquerade as empty.
This diagnoses whether the real E1 failure `invalid unexpected collection`
was an unrecognized metadata container without weakening strict original
full-tensor source-byte checks, independent numerical review or `DENY_ALL`.

The five additional adversarial, model-free checks bring the suite to 23/23
normal and 23/23 `python -O`; only an exact hosted V16.2 CPU run can confirm
which native collection the original weight loader actually produced.
