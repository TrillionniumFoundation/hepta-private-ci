# Bounded causal generation and metered System2 controls

Remote base: `08cb87a6df5fb0c68b9db3f1bb00d67579bf68c4` (PR #1757).
Tested LOCAL source-slice commit: `77384a65d1f778cf140afd4b0793c85ee2263542`.
Local branch: `research/shared-stem-causal-generation-controls-20261014`.
This increment was NOT pushed: the current connector exposes reads, not Git-data
writes, and direct Git transport failed to resolve github.com. No new remote PR,
main merge, selected-model mutation or deployment occurred. Local slice history
is not a full-repository ancestor; apply the delivered patch to the remote base.

## Generation now comes from token logits

`causal_generation.LocalCausalProposer` plugs directly into the existing proposer
callback. It renders only PublicTask plus the previous candidate/feedback as a
bounded JSON prefix, calls an actual causal torch model, selects one greedy token,
then repeats until EOS. It never looks up a target answer. The prompt format is
explicit, not silently converted into a model-specific chat template. An admitted
model still needs evidence that it can use this particular prompt/revision format.

The adapter binds actual parameter/buffer contents, serialized fast-tokenizer graph,
vocabulary, EOS, context/output limits and a decoding profile. Weights must already
be frozen CPU FP32 eval tensors. Inputs exceeding the full prompt-plus-generation
envelope reject before model execution; there is no silent truncation. Missing EOS,
empty output, nonfinite/wrong-shaped logits, returned KV state and byte-budget
violations cannot return a partial string as a complete answer. Failed attempts
retain token-prefix/forward observations in the existing callback trace.

One model object can be referenced by multiple adapters without cloning its weights.
The reference path is serial and deliberately rebuilds every full prefix with
`use_cache=False` and no incoming KV. Interleaved requests leave no adapter-owned
KV state, and greedy generation does not consume the global RNG. This costs MORE
recomputation than a qualified KV implementation; it is not an efficiency win.
Parameter/tokenizer digests are rechecked before/after successful generation. Hashing
and tokenization cost CPU even where their floating arithmetic contribution is zero.

The full-prefix logit payload has a 256 MiB preflight bound. That is not a process
or activation-memory limit. Arbitrary Python models can have hidden state, hooks,
side effects or different unregistered code despite the same tensor contents.
Those need owner/source review; neither hashes nor this adapter are an OS sandbox,
complete model-code attestation or universal counterfactual-state reconstruction.

## Real local snapshot entry point, narrowly scoped

`causal_snapshot.load_local_causal` supports reviewed stock tied GPT2LMHeadModel
snapshots under Transformers 4.57.1. It requires an already present, content-pinned
local directory and external material-approval reference. It bounds model geometry
and safetensors bytes BEFORE constructing the model, requests local-only safe
weights/eager execution, and compares actual tensors using the existing verifier.
The lm_head/input-embedding omission is allowed only with the same physical view.
No pickle fallback, automatic download, missing-weight initialization or lossy
checkpoint conversion is admitted. Snapshot bytes are rechecked after loading.
This is an interface profile, NOT a recommendation that GPT2 is Hepta's best Stem.

The current session lacks Transformers/tokenizers, so real stock-HF loading was
NOT executed locally. Six local loader tests use mocked HF factories but actual
PyTorch tensors and safetensors bytes. The separate `hf_generation_checks.py` uses
the real stock architecture without network or pretrained claims and is added to
the existing HF CI job. Its dependencies and job have not run for this unpublished
patch. The check does not disguise arbitrary errors as expected EOS exhaustion.

Reference interface inspected: Hugging Face GPT2 model/forward documentation,
https://huggingface.co/docs/transformers/v4.57.0/model_doc/gpt2 .

## Actual control baselines, not manufactured value estimates

`reasoning_baselines.freeze_baseline` declares no_search (one propose/verify pair)
or fixed_depth (at most a declared number of pairs). Both execute inside the SAME
run_reasoning loop and same work-ledger mechanism. They never call a dummy critic
or inject an artificially high continuation utility. They stop on the same verifier
acceptance rule; fixed depth is an upper bound, not forced useless extra work.
The exact policy, caps, expiry, calls and rounds must match the supplied meter.
Expiry inside a fixed-control callback also rejects its result.

Fixed, paired-capture and NDU policies are mutually exclusive. Legacy unmetered
callbacks still work without importing torch. The older scenario/empirical NDU and
one-segment capture paths retain their behavior. Model observations are copied into
existing traces, including interrupted generation; receipts cannot mutate adapter
state. New source files participate in capture source fingerprints, so replay uses
the exact registered source version. Existing nine-arm model training is unchanged.

The fixed callback-profile digest is an owner reference, not verification of arbitrary
callable code. The diagnostic genuinely reuses the same proposer/verifier objects.
COMMON CAPS ARE NOT EQUAL ACTUAL COMPUTE. No data were padded with dummy work to make
the controls appear matched, and no matched-quality resource conclusion is drawn.

## What the learned diagnostic does and does not show

The extra diagnostic trains a 1,091-parameter prefix network on 15 next-token
examples over three colour prompts, for 240 optimizer steps. Its output is learned
through real PyTorch optimization: initial proposals emit `unsure`; revision prompts
emit two tokens such as `red done`, followed by EOS. Every token-position logit is
causal; appending a future suffix does not alter earlier logits. It is an intentionally
simple order-insensitive prefix network, NOT a pretrained/generalizing language model.
This closed-vocabulary curriculum teaches the initial/revision distinction; it does
not discover reasoning from unsupervised Cell division.

The same trained generator provides the initial candidates and three actual paired
continuations. A separate test oracle supplies exact-string utilities only after
sealing. The resulting critic has one fitting group and two calibration groups;
its support gate correctly remains FALSE. No repeated/near-duplicate examples are
relabeled as many independent groups to manufacture confidence.

On the same test prompt and common declared caps:

| Control | Actual callbacks | Model forwards | Output | Observed formula work |
|---|---:|---:|---|---:|
| No search | 2 | 2 | unsure | 21,585 |
| Fixed depth <=2 | 4 | 5 | red done | 81,267 |
| NDU using captured under-supported critic | 3 | 2 | unsure; unsupported stop | 21,585 |

The lookup's Python work is not zero cost merely because the ATen count is unchanged.
These are instrumented mechanism observations, NOT a held-out capability, confidence,
latency or energy benchmark. Separate regression tests use explicitly synthetic
positive critic data to verify that NDU can invoke the REAL neural proposer twice;
that is not called independent calibration of this learned generator.

## Verification, including tool timeouts

The unchanged remote-base source slice passed 342 tests. New tests total 33:
14 generation, 6 safe-snapshot, 8 control, 5 neural capture/integration. Two standard
full-suite logs each contain `Ran 375 tests ... OK`, but their surrounding tool calls
timed out without an exit marker. A third evidence worker was interrupted before its
summary. Those logs are retained; their process exits are NOT reported as zero.

All 375 distinct tests were then covered EXACTLY ONCE in four ordinary unittest
processes, partitioned by test module: 100, 75, 109 and 91 tests. Each process actually
returned exit code 0, with no errors, failures or skips; unique test IDs and full module
coverage were checked. This verifies the complete focused suite, not a full repository
build. The earlier full 374-test run is development evidence for the previous graph,
not the final test count. No arithmetic registry or scientific threshold was relaxed.

Compileall, diff whitespace and workflow YAML parsing passed. The independent old-HF
check failed at import with missing transformers (0/3 executed); the new stock causal
check failed at import with missing tokenizers (0/1 executed). Neither is included in
375 passes. No project-cloud/GPU/native/Rust/full-repository/hosted-CI result is claimed.
The source slice has neither codex-rs nor just for the repository-wide Rust formatter.

Standard reproduction:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
# In the separately provisioned exact HF environment:
python qualification/stem-cell-v1/hf_generation_checks.py -v
```

Use load_local_causal with approved local weights, retain the returned profile, bind
the SAME actual verifier to capture and runtime, and call run_reasoning with either
fixed_policy or the existing fitted NDU policy. The executable integration tests
show these calls; their toy data and numeric thresholds are not deployment defaults.

## Still required

Approved real model/task material, an appropriate prompt adapter, learned/calibrated
critic support, independent final panels, equal-total-cost comparisons and complete
energy/memory/evaluation accounting remain open. No nine-arm NDU activation, native
utility.ndu owner, learned multimodal generator, multi-generation retention,
1024/4096-Cell service or 10T/100T equivalence is established by this increment.
