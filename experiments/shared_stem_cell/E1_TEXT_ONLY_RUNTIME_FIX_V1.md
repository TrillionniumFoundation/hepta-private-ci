# E1 text-only CPU runtime fix V1 — research / DENY_ALL

Exact parent: P0 research #2378 at `b0586cdd8c856a63693542aca92086e73b98d69b`.

## Actual hosted failure

E1 real AG News CPU run `38888885968`, job `116933271032`, failed in the
**pinned CPU runtime installation/smoke step**, BEFORE source-locked pretrained
feature encoding. The installed optional `torchcodec==0.10.0` import required
FFmpeg shared libraries that were absent from the Ubuntu Runner, producing
`RuntimeError: Could not load libtorchcodec` and missing `libavutil.so` errors.
This is an environment error, not a failed Stem task score or model benchmark.

## Minimal correction

Remove the optional video/audio `torchcodec` package from the TEXT-ONLY E1
research workflow and omit its import from smoke. Keep all original pinned
Torch 2.10.0 CPU and torchvision 0.25.0, Transformers 5.19.0, NumPy,
safetensors, source SHA/LFS checks, original AG News input identity, each
original model's immutable revision, actual three-model CPU encoding, actual
40-step Head training, and independent model/snapshot/numerical reviews.
No fake model result, code-path fallback, ignored dependency exception or
weakened FailClosed gate is introduced.

A new standard-library regression suite executes **before** the heavy model
installation and refuses reintroduction of an optional media codec, removed
pinned model package, skipped independent reviewer, malformed/duplicate
install-step boundary or disabling dependency resolution. It also tests both
normal and optimized Python modes. Runbook method tests may use a small local
workflow fixture; exact GitHub CI checks the actual checked-out workflow.

## Qualification boundary

Seven model-free source tests passed locally in normal and Python `-O` modes.
This does NOT attest FFmpeg provisioning, an actually successful new hosted
runtime, pretrained model loading, real human task efficacy, or production
FinalUse. Current P0 four-model run and V15 mmBERT physical proof remain
strictly separate; this branch must stay **DRAFT / DENY_ALL / NO MAIN MERGE**.
