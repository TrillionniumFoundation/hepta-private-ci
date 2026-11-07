# Image-adapter fingerprint repair

Status: **LOCAL_CONTRACT_PASS / REAL_CANARY_FAILED_PARTIAL / SCIENTIFIC_HOLD**.

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

## Actual corrected-source execution

The corrected [run 42367863157](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42367863157),
job `128389640910`, executed source
`1e869d455fe2fb53b5221b84bc0a27e190b09ab2`. GitHub terminated it at the
30-minute job limit. The check-run annotation explicitly records that limit;
the outcome is **Failed / partial evidence**, not completed training or NoUpdate.

- Text: two updates completed, the frozen backbone hashes stayed equal, and
  same-input checkpoint reload logits matched exactly (maximum difference zero).
- Image: admission, real SD loading and the complete initial parameter hash
  finished. The former bfloat16 stride exception was crossed on real weights.
  No update-start or update-complete event exists. Execution did not produce
  the next `prepare_real_vae_and_clip` completion event. Without a stack sample,
  the specific operation inside that interval is not established.
- No image final report/cost receipt, aggregate training summary or adapted
  dual inference result was produced. The outer training meter remained
  `started` when the workflow was cancelled; final CPU/wall cost is unknown.
- GitHub records 1,818 seconds for the job and 1,732 seconds for the training
  step, including cancellation/orchestration. These timestamps are not final
  process CPU meters and must not be added to enclosed wall-time intervals.

[CANCELLED_ATTEMPT.json](remote-evidence/CANCELLED_ATTEMPT.json) retains the
completed command meters and the known training lower subtotal. Unknown cost
is null, not zero. [ORIGINAL_ATTEMPT.json](remote-evidence/ORIGINAL_ATTEMPT.json)
keeps the previous failed attempt and its separate command costs. Both runs
used the same model pins, data manifests, seed and original training limits;
they are not independent training replications.

[CANARY_AUDIT.json](remote-evidence/CANARY_AUDIT.json) independently recomputes
the saved tensor fingerprints and compares the actual inputs, model manifests
and plans. The two text checkpoints contain identical tensor headers and data;
their file hashes differ because their source metadata differs. The installed
environment was not completely identical: the unpinned transitive `regex`
package changed from `2026.9.29` to `2026.11.7`. That difference is recorded.

The original ZIPs are retained byte-for-byte, with the API artifact digests:

| Attempt | Original artifact | SHA-256 |
| --- | --- | --- |
| Historical fingerprint failure | [original-failure-e23dfea.zip](remote-evidence/original-failure-e23dfea.zip) | `21ed6b0bed552909fee6738ae39e7327e3862f39a9b28cd4a1d329ee9be8eb39` |
| Corrected source, deadline cancelled | [canary-cancelled-1e869d.zip](remote-evidence/canary-cancelled-1e869d.zip) | `8f9fe6239dcaaaa646fdab09fc42c38289ccbe7fb9483f67f8d85a6dff5ed7f8` |

[workflow-readback.zip](remote-evidence/workflow-readback.zip) preserves the
workflow metadata, cancellation annotations and complete job log. Each original
archive contains a 798,320-byte learned checkpoint that cannot be compressed
under the default blob limit. The existing intentional-asset mechanism lists
only these two exact archive paths; the global size limit remains unchanged.

This execution establishes the fingerprint repair and text checkpoint wiring.
It does not establish held-out quality, a full controller factorial, joint-return
training, retention, complete study cost or adoption. The incomplete execution
also motivates an independently bounded command meter so cancellation can leave
a final outer receipt. **NO_GO_FOR_LARGE_SCALE_TRAINING** remains in force.

[BROAD_CI.json](remote-evidence/BROAD_CI.json) separately records the broader
repository CI failures, including unchanged spelling, root-readiness, Windows
path and Rust/Bazel checks. No all-CI pass is claimed. A different hosted native
smoke job completed and retained original owner receipts; its detailed custody
and authority limits are published with the dependent research evidence in
[PR #5311](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5311).
