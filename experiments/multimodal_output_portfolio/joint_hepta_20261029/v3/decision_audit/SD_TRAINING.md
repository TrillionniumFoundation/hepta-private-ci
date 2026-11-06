# Real tiny-sd development training and cold replay

This adapter continues the actual `segmind/tiny-sd` path fixed by PR #4857
(`de2b1212242cfa6f25563b99a385497a86dc7e49`). It does not create a replacement
model and does not change `LocalModels`, the frozen reference, or production
selection. The complete R2 protocol remains partially frozen.

## Smallest executable training slice

`sd_train.py` loads the reviewed base revision
`cad0bd7495fa6c4bcca01b19a723dc91627fe84f`, using the existing acquisition
manifest and weight pins. Loading is local-only and preserves the original
`weights_only=True` checks. This separate development adapter uses CPU FP32,
at most two threads, deterministic PyTorch operations, one image resized to
256 by 256, the deterministic VAE posterior mean, a seeded timestep and noise,
and an epsilon-prediction MSE objective.

The existing UNet's `conv_out.bias` and `conv_out.weight` are the complete
trainable allowlist. SGD uses explicit learning rate, momentum 0.9 and one to
eight predeclared updates on that single batch. Each actual backward must
produce finite gradients. Both allowed tensors and the actual noise prediction
must change. Every other UNet state entry, all VAE state and all text encoder
state must remain byte-identical. This is a mechanism qualification, not a
claim that training the last projection is an effective adaptation method.

`sd_checkpoint.py` stores the two changed tensors, optimizer momentum and
generator RNG state as safetensors. The manifest binds the complete before and
after tensor inventories, fixed base manifest, exact input, plan, source files,
package versions, loss values and real denoising probe. It is written last.
Partial directories remain retained but cannot qualify as a completed fit.

Cold replay requires both the externally retained checkpoint SHA256 and the
completed training receipt SHA256. It loads the base again in a new process,
rejects mismatched lineage, roster, shape, dtype, bytes or nonfinite values,
applies the delta, and requires exactly matching batch and prediction hashes.
The optional `--render` executes the real pipeline for twelve diffusion steps
with the original safety checker retained and saves a 256 by 256 PNG. Rendering
does not evaluate semantic quality.

## Invocation

Run the modules from the repository root on Linux. The plan must bind
`schema=hepta.r2.sd-development-plan.v1`, `split=development`,
`confirmatory_fit=false`, `source_sha`, all four `source_files` SHA256 values,
`image_path`, `image_sha256`, `prompt`, the exact `trainable` list,
`resolution=256`, `momentum=0.9`, `steps`, `threads`, `seed`, `learning_rate`,
and explicit CPU and wall limits. The limits apply separately to each invoked
process; they are not the numerical budget of the full R2 study.

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.sd_train fit --sd /absolute/models/sd --plan /absolute/dev-plan.json --output /absolute/new-fit
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.sd_train replay --sd /absolute/models/sd --checkpoint /absolute/new-fit/candidate --sha256 CHECKPOINT_SHA256 --fit-result-sha256 RESULT_SHA256 --output /absolute/new-replay --render
```

Output directories are create-only. Failures and interruptions retain a
`STARTED.json`, any partial files, and a terminal receipt when Python regains
control. SIGKILL, process/host loss or a final write failure can leave an unknown
outcome; absence of `RESULT.json` is never success. The CPU limit has a hard
kernel limit five seconds after its soft threshold. Python alarm handling is
not a hard wall deadline inside native code; a supervising process deadline
and its receipt must also be retained.

Costs report the inclusive process CPU envelope, wall through receipt
preparation, Linux peak RSS and actual retained bytes before the final report.
Nested timings must not be added to this envelope. Energy, network bytes and
final receipt/exit costs remain explicitly unknown where unmeasured. Training,
cold replay, rendering, setup, validation and publication remain distinct.

## Acceptance boundary

The old R1 bee image may be used only as an exposed development fixture. It
cannot become a new source cluster or an independent test. Unit fixtures and
one real update do not establish a complete fit, controller learning, NDU
benefit, the four-arm interaction, generalization, quality floors, sufficient
power or complete lifecycle economics. No test custody is created here.
Candidate output stays research-only and cannot replace the incumbent.

Before any actual execution, source, plan, model and input identities must be
fixed. Fresh raw receipts, including failures, are appended separately after
execution; the existence of this implementation is not execution evidence.
