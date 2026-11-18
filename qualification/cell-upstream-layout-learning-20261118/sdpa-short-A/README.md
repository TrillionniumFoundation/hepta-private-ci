# Prospective short-A eager / SDPA calibration

Three completed prior attempts failed under the unchanged 70% CUDA allocation cap. The expandable allocator allowed the eager forward to complete, but its backward still exceeded the cap. This is a new engineering calibration, not a new scientific result or a reinterpretation of those failures.

Before any new model computation, freeze one already exposed A record, both original evidence layouts, and four full forward/backward attempts (eager then SDPA within each layout). Only masked padding changes to 1024 for this short calibration; all 773 / 777 original input positions and 115 supervised targets remain. No optimizer is created, no generation is performed and B3 remains sealed. The real full-length 3584 group must still pass separately before training.

Compare every selected logit and every LoRA gradient. Fixed limits: absolute cross-entropy difference <= 0.02, maximum absolute logit difference <= 0.5, argmax agreement >= 0.97, gradient relative L2 error <= 0.05 and gradient cosine >= 0.995. Also require finite tensors, actual fused SDPA autograd evidence, no math fallback, and byte-identical parent parameters after calibration. Record every parameter's norm and zero count. A numerical rejection is retained without retrospectively changing these limits.

The original 2D padding mask, RoPE/configuration and native causal-mask construction remain in effect. The backend context surrounds both the forward and checkpointed backward. SDPA is a distinct floating-point and kernel implementation; this does not assert bitwise equality, equal FLOPs, equal wall time or equal energy. Inference is not changed by this probe.

Full raw tensor files are retained on the authorized desktop with exact SHA256 and sizes; source, protocol, metrics and paths are reviewable in this branch. Whole-host RAPL includes unrelated system work. GPU energy and complete monetary cost remain unknown.
