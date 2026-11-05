# Pinned real local generator adapters

This third review stage supplies reproducible model acquisition and real
pretrained CPU inference adapters. The next execution stage supplies the public
controller view, actual media/cost runner and source-bound canary workflow.

| Role | Model | Immutable revision |
| --- | --- | --- |
| Image encoder and text generator | HuggingFaceTB/SmolVLM2-256M-Video-Instruct | 067788b187b95ebe7b2e040b3e4299e342e5b8fd |
| Image draft and refinement | segmind/tiny-sd | cad0bd7495fa6c4bcca01b19a723dc91627fe84f |

All four weight files have fixed sizes and SHA-256 identities in source. Every
downloaded config/tokenizer/weight file is hashed in a materialization manifest.
The local loader checks manifest identity and bytes, disables remote model code,
and freezes model parameters. SmolVLM contains a pretrained visual encoder and
language decoder; tiny-sd is a distilled diffusion model, not the random
internal-testing pipeline. This choice establishes a real small-model test,
not foundation-model quality or accurate scientific drawing.

The adapter uses explicit CPU bfloat16, a 512-pixel single-image view without
image splitting, and at most one model family resident
at a time. Switching models releases the previous objects and is charged by
the calling execution interval. Re-loading costs cannot be described as free
cache reuse. `load()` is only an explicit qualification operation; ordinary
`describe` and `draw` perform lazy loading when an action is actually requested.
The tiny-sd checkpoint uses pinned `.bin` weights; the declared PyTorch version
and actual diffusion loader must enforce `weights_only=True` before loading.

`acquire_models --root PATH` downloads one copy without a duplicated Hub cache.
Each invocation appends START/FINISH records to `ACQUISITION_ATTEMPTS.jsonl`,
including failed and cancelled attempts. `--preflight-only` only observes the
resource envelope. It cannot establish a successful download or inference.
The public image uses the fixed documentation-images dataset revision
`4be1ef917419575e5f13bc54939a3f57aa22deff`. Actual acquired image identity is in
`task/INPUT_MANIFEST.json`; execution records its deterministic resized input.

Six local contract tests exercise streamed hash/size checks, failed and
cancelled acquisition retention, incomplete manifest rejection and identity
before loading. No actual model forward is inferred from those fixture tests.
The actual pinned SmolVLM processor also encoded the public image into a
single `[1,1,3,512,512]` pixel tensor and 82 prompt tokens. This small API
compatibility check loads no weights and executes no model forward; its
receipt is `evidence/PROCESSOR_PREFLIGHT.json`.
The authoring host was at its shared 8 GiB memory cap and full disk; large-model
execution was transferred to a bounded dedicated research executor.

Primary model documentation:
[SmolVLM2](https://huggingface.co/HuggingFaceTB/SmolVLM2-256M-Video-Instruct)
and [tiny-sd](https://huggingface.co/segmind/tiny-sd).
