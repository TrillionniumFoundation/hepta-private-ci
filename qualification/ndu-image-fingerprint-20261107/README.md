# Image-adapter fingerprint repair

Status: **LOCAL_CONTRACT_PASS / REAL_CANARY_PENDING / SCIENTIFIC_HOLD**.

Parent source: `e23dfea486025e09d7e11dd17ea0852d6e3e89d0` (#4839).

## Observed failure

The original [research run 41976044300](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41976044300),
job `127075010670`, completed with failure. The text adapter completed two
updates; the image adapter completed zero updates. Its parameter fingerprint
raised:

```text
self.stride(-1) must be 1 to view BFloat16 as Byte (different element sizes), but got 320
```

Adapted dual inference therefore remained `not_run_unqualified_training`.
The original run reports 193.311381964 CPU seconds and 140.111789741 wall seconds
for its training envelope. These inclusive measurements are not additive with
their enclosed action meters. The historical failure is retained, regardless of
whether the corrected source passes later.

## Repair

The old `contiguous().view(torch.uint8)` path assumed that a contiguous tensor
always has unit stride on its final dimension. A singleton dimension can violate
that assumption, and flattening a one-element tensor can still retain a stride
of 320. The repair flattens logical values, explicitly copies a non-unit-stride
one-dimensional result, and then reinterprets its bytes without a dtype
conversion.

The existing shape/dtype hash domain remains unchanged. Normal supported layouts
retain the same fingerprints. Regressions cover bfloat16 NaN payloads and signed
zero, singleton dimensions, scalars, transpose, storage-offset slices, expanded
views, empty tensors, and parameter identity/gradient-state preservation.

The only workflow change adds this exact branch to the existing push trigger.
The original model pins, single disclosed source, zero holdout sources, two
updates per generator, fixed dual schedule and execution budgets are unchanged.

## Local verification

[VERIFICATION.json](VERIFICATION.json) binds the changed source and the original
logs stored byte-for-byte in [local-logs.zip](local-logs.zip). Log hashes refer to
the decompressed files; original unittest trailing spaces are preserved.

- Before the repair: three new tests reproduce four errors, including the exact
  bfloat16 stride failure and the scalar byte-view failure.
- First full-scope attempt: 68 tests, with errors from an absent unchanged
  sparse-checkout oracle dependency. That failed attempt is retained.
- After materializing the exact same-source dependency: **68 passed, zero
  errors, zero failures, zero skips**, using Python 3.12.14 / Torch 2.8.0+cpu.
- `just fmt` and `git diff --check` succeeded. The formatter reported no changed
  files in its owned formatting scope.
- Installation and local test CPU/energy costs were not fully measured and are
  not treated as zero.

The remote canary must bind its own new source SHA. A new workflow submission
is not a passed model experiment. Even successful execution remains development
qualification: no independent held-out quality, full controller factorial,
joint-return training, retention, complete study cost, native owner closure or
adoption is established. **NO_GO_FOR_LARGE_SCALE_TRAINING** remains in force.
