# V25: fix actual Qwen3 0.6B reference Loader failure on pinned Transformers 4.53.3

**RESEARCH_ONLY / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. No main merge, Model/Cell selection, or FinalUse.**

## Observed physical blocker

The original GitHub Actions public model smoke at commit `c9c2b470dd6b5c9ece89a972ee5f66e3b3e6bea7`, run [38903841863](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38903841863), job `116982384366` actually reached `Pin public Qwen bytes and execute one genuine public-input model forward` and **failed before the first pretrained forward**. Torch 2.6.0+cpu, Transformers 4.53.3 and related dependencies were installed. The exact historical Qwen model revision `16706fc57485378d4ffaf54139b29ccc66ae08fa` was materialized (7 files admitted) before the failure.

Actual model-constructor error:

```
TypeError: Qwen3ForCausalLM.__init__() got an unexpected keyword argument 'dtype'
```

The two original live entry points `v18_reference_public_smoke.py` and `v17_reference_reader_physical.py` both passed `dtype=torch.float32` to `AutoModelForCausalLM.from_pretrained`. On the pinned Transformers 4.53.3 runtime this is an unsupported constructor argument; it must be named `torch_dtype=torch.float32`. This is an API compatibility issue, **not a failed task answer or a numerical Reader result**.

## Bounded correction

- One new `v25_pinned_qwen_loader.py` function explicitly passes `torch_dtype` and preserves `local_files_only=True`, `trust_remote_code=False`, `use_safetensors=True`, and `.eval()`. Both original call sites share the same function; neither changes original model/source SHA, prompt, Qwen generation policy, input cap, evidence roster, or the owner's evidence/FinalUse controls.
- `test_v25_pinned_qwen_loader.py` injects an exact-keyword tracing model loader that rejects the historic `dtype` spelling. AST validation requires *both* entrypoints to use the shared adapter, guarding against a second silent regression.
- The public pretrained workflow runs this source suite under normal and Python `-O`. After dependency installation, but **before any model material is downloaded**, it builds, saves and reloads an explicitly tiny random **Qwen3Config** through the very same helper using actual installed Transformers 4.53.3 + CPU Torch, verifies synthetic FP32 logits and the safetensors SHA, and prints `SYNTHETIC_QWEN3_CONSTRUCTOR_COMPATIBLE_NOT_PRETRAINED`.
- Only after the above passes does the original SHA-pinned actual Qwen model stage and 1-public-prompt neural forward execute. It re-hashes the real model files after load and generation and publishes **digests/cost only**, never private LoCoMo input or output strings.

## What has and has not happened

The newly authored source and mock/AST tests can be verified in the authoring environment without pretrained tensors or Transformers installed. The tiny-Qwen loader test is **not** a pretrained Qwen run, and its success does not prove task ability. Actual Qwen **public smoke** and the private **128-request historical matched comparison** must each reach separate terminal status and independent postseal byte/semantic scrutiny. The first is a compatibility prerequisite only.

Do not inherit a green check from a different SHA; preserve `blocking-ci`, Architecture, versioned source ownership, private evidence scope and all product restrictions. No shared Stem/Cross-Cell/NDU/FBSDE or 10T/100T claims arise from this correction.
