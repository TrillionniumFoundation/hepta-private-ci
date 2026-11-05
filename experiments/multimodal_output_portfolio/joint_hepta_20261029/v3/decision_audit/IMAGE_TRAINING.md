# Real diffusion-output parameter adaptation

This module is a bounded single-image training wiring check. A separate FP32
low-rank 1x1 residual is attached to the real tiny-SD UNet output convolution.
UNet, VAE and CLIP base parameters stay frozen. The residual returns the base
output dtype so diffusion inference remains compatible with the CPU BF16 model.
This is not a claim that a 1x1 residual is a full 3x3 convolutional LoRA.

Each update runs the real UNet on noisy image latents. The DDPM training target
follows its declared epsilon, velocity or sample prediction convention.
Real VAE/CLIP preparation is performed once and charged as a frozen cache.
Prompt token overflow is rejected; the training interface never silently
truncates CLIP conditioning. Image bytes and the training-only manifest must
match their independently supplied hashes.

The manifest schema is `hepta.real-image-adapter-training-data.v1`, role
`training_only`, and exactly one example with `source_id`, `image_path`,
`image_sha256`, `prompt` and `target_provenance`. The target is the declared
image itself; a photo reconstruction target does not establish diagram training.
Repeated optimizer exposures are not independent sources.

```bash
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.train_image_adapter --models /tmp/dual-models --manifest /tmp/image-train.json --manifest-sha256 FROZEN_SHA256 --output /tmp/image-adapter --source-sha EXACT_SOURCE_SHA --steps 2 --rank 4 --threads 2
```

The report binds all original UNet/VAE/CLIP parameter hashes, adapter parameter
hashes and changed counts, finite gradients, actual forward counts, random
noise/timestep identities, input preprocessing, source code and checkpoint.
Two updates normally entail five UNet forwards: two updates plus trained,
unadapted and reloaded probes on the same final noisy input. Reload must be
elementwise identical and retain dtype. A small FP32 parameter update can be
rounded when cast to BF16; changed parameters do not guarantee changed pixels.

`load_image_adapter(unet, path, expected_sha256)` verifies the exact checkpoint
and complete UNet fingerprint, freezes the loaded residual and returns its
removable hook. Successful admission requires both `status == "completed"`
and `checkpoint_qualified == true`. The `checkpoint` field can retain a
physical artifact after failure; its existence is not an admission decision.

Full hashes, preparation, updates, failures, save/reload, probes, report writes
and cleanup are charged. Time allowances are boundary checks, not preemptive
deadlines. Final hash failures and final-write overruns retain failed/timeout
receipts. Invalid nonfinite configuration is represented safely in failure
reports. Final meter overhead and process startup remain explicit outer costs.

This interface alone establishes no controller learning, joint-return gradient,
four-arm interaction, independent semantic acceptance or production readiness.
Behavioral tests use small neural stand-ins; a separate exact-source run must
demonstrate actual pretrained training.
