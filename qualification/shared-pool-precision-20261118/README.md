# Preserve FP32 adapters on the admitted BF16 shared base

The admitted PEFT 0.18 `load_adapter` creates a later adapter using the base's
BF16 dtype, copies the saved FP32 weights, and only then promotes them to FP32.
The intermediate conversion loses bits and correctly fails the original
`TRAINING.parameter_after` hash gate. The first `from_pretrained` adapter uses
a different initialization order; a float32-only tiny test missed this defect.

The production change preserves config validation, creates the next named
adapter, promotes only that adapter before copying, and calls the original
`load_adapter`. The base remains BF16. Original activation, complete tensor
hash, parameter count, resident count, base identity, and cleanup checks remain.
This fix is specific to the admitted PEFT version and does not qualify a new
backend, independent learning result, native adoption, or Circuit business gain.

The new real CPU regression uses a tiny BF16 Qwen model and three FP32 LoRA
fixtures whose weights cannot survive a BF16 round trip exactly. It checks
all saved bytes for second and third non-default adapters, C/F/T/C switching,
repeat logits, and unchanged base object, dtype, and bytes. Separate raw-bit,
dtype, name, iteration-order, and declared-count mutations must all be rejected.

The unchanged original pool fails this regression at the actual training-after
hash gate: one test, one error, zero skips, PID 3168036, real wait exit 1.
The fix passes the new regression, the existing real A/B/A test, and eight
cleanup regressions: ten tests, zero errors/failures/skips, PID 3170788, real
wait exit 0. CUDA is unavailable in both child processes by explicit environment.
These are engineering fixtures, with no research model training or generation.

[RAW_EVIDENCE.tar.gz](RAW_EVIDENCE.tar.gz) retains 20 source/receipt files plus
their size/SHA index, including the original failure and both process chains.
Archive size: 16,747 bytes; SHA-256:
`b87c00f4feba5f48b9e75415dbf074d6df7703ffbaaee171c930a865f0146ea2`.
The repository's original `just fmt` exited 0; both pre/post-format ASTs match.
Formatting did not trigger another test run. The production final SHA-256 is
`110b33222dc620ce5fb61b1e4ff9fb4b4e5f7bb03ee25a4c9c726e99f7476d3c`;
the new regression final SHA-256 is
`bd78c6af6d2fad670a1ea70d535c2518616d03658945a0adba05de81d15f33b2`.
