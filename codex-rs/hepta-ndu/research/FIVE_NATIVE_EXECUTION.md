# Five causal experiments: native backend increment

2026-10-13. Parent: `8a30d4cc4b1414944e0cfcc4e26a3db3bee0daf4`.
Research-only, same PR #1697. No production model selection or main merge.

## What changes

The previous round provided contracts, not native model adapters. This increment
adds actual offline Reader and Head execution through the existing five-causal
packet and journal formats. `experiments/shared_stem_cell/execution.py` is reused
BYTE-FOR-BYTE from PR #1699 at `3b9e743c45c808bb25712c0c583001943adb5599`, blob
`ba7bb1d9526444c8962c3dbb567dd8f0713f8511`; it is not a second reimplementation.
The source loader verifies all snapshot files and materialized safetensors,
including tied aliases. There is no remote-code or automatic download fallback.

`scripts/memory_cell/five_causal_native.py` implements a native one-shot ABI,
resident research session, actual train-only Head optimization and a signed
registered-run entry point. Model ownership is shared per scope, purpose,
generation and comparison arm; replicated mode creates distinct model objects
per cell. The owner records physical loads, forward calls and Head tensors.
Input caching is bounded and exact-input keyed; it defaults to disabled. Model
calls, actual load/training time and tensor counts are not called FLOPs/energy.
Unknown counters remain null. The process-level time limit is checked at model
boundaries, not a claim of hard GPU/kernel preemption.

Each content-addressed native bundle lives at `bundles/<SHA256>.json`, with the
SHA of its exact canonical JSON bytes. It binds model path, complete snapshot,
Cell/scope/purpose/generation, sharing mode, fixed preprocessing and optional
head safetensors/shape/architecture. Reader prompt, tokenizer and decoder are
bound separately. Model packets never include training targets, reviewer labels
or arm names. Head training accepts only train rows and saves both unchanged
initialization and fitted checkpoints with reload checks. A generic text Head
is not a Laya decision model or a full-model fine-tuning baseline.

The registered-run path still requires the independent preregistration and
Reader admission used by the five-causal plan, including dual signatures and
out-of-band reviewer roster. It implements E1 Reader and E2 Head inference only.
It explicitly rejects Group/System2/NDU and real-media execution until those
adapters exist; it does not silently simulate them.

## Actual execution state at source publication

The current local container initially ran file/environment checks: Python
3.13.5, CPU torch 2.10.0, no Transformers or cached pretrained models, DNS failure
for GitHub/Hugging Face. The GitHub connector recovered the historical native
feature archive (11706235289) and verified its outer SHA in the working runtime.
It then downloaded the actual model/data artifact (11586991191, 376363859 bytes).
After that download, repeated container/Python calls failed with infrastructure
`ClientError`, including a `true` command. No native inference or new tests were
completed locally. DO NOT reuse the preceding round's 68 passes as this source's
verification. New tests and exact-source hosted execution are pending their
actual results. No new passing test count or model accuracy is asserted here.

Original model/data artifact provenance:
- run: 37862780268; artifact: 11586991191; name: memory-native-staged-inputs;
- externally reported SHA256: 07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af;
- packaging source commit: 4e996a707a7717152ab36cccaed901c4bd8248a2.

The archived material has pretrained weights, not an independently released new
cohort. It is used ONLY by `five_native_historical_smoke.py`. This diagnostic
pins the outer ZIP, rejects unsafe archives, verifies original per-file model
inventories and source dataset, selects four existing question identities before
reading target annotations, and executes 16 Reader attempts. Conditions are
no evidence, lexical retrieval, original annotated source support, and removal
of the whole support group. The annotation is NOT independently human-verified
sufficiency. The removal equals empty evidence in this deliberately limited
smoke; it does not establish partial-premise sensitivity. No signed review is
created. Exact-answer/refusal diagnostics are calculated only after all original
answers have been fsynced and sealed.

The same diagnostic then encodes up to 32 historical questions and performs 32
actual optimizer updates on a category-classification Head. This is a native
training/serialization check, NOT new task behavior, source-ranking gain or a
shared-vs-replicated equal-quality result. The archive packaging commit is used
as a packaging revision, explicitly NOT relabelled as a Hub model revision.
All original model/tokenizer bytes remain independently pinned by inventory.

## Reproduction

```sh
python -m unittest discover -s scripts/memory_cell -p test_five_causal_native.py -v
python scripts/memory_cell/five_causal_native.py train --root /approved \
  --plan /approved/train-only.json --output /new/head-candidate
# Requires exact externally approved inputs and all independent review pins:
python scripts/memory_cell/five_causal_native.py run --root /approved \
  --plan /approved/bundle.json --review /approved/preregistration.json \
  --experiment reader --output /new/reader-run
# Historical integration check, NOT confirmation or a route around the gate:
python scripts/memory_cell/five_native_historical_smoke.py \
  /path/to/pinned-original-model-artifact.zip /new/historical-output
```

The scoped read-only workflow runs all existing matrix/five-contract tests, then
new native tests, and only then actual original-weight inference/training. It
retains failures and exact source without uploading pretrained model weights.
No synthetic fallback, credential creation, new paid provider calls, main merge,
model promotion or change to the original 768-row admission gate is made.

Still open: truly unseen independently reviewed cohorts; learned nontrivial
Group reasoning; NDU compute allocation; media backends and independent split
benefit; full lifetime cost, native Rust owner integration and target GPU serving.
