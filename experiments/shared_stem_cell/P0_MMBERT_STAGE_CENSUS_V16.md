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
runtime: source SHA/LFS preflight, AutoModelForMaskedLM loading, strict V15
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
