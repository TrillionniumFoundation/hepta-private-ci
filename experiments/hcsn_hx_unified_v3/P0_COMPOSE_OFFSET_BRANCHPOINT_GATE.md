# P0 stacked renewal-boundary composition gate (research only)

Status: **DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false**.

## Immutable refs and deliberately narrow scope

- Destination parent: PR #4451 HEAD `b0939f97930b15e6b06d89979eb5cbed52373c45`, source blob `98344428ba06691c01e6b5b5bd3c10c455982f80`. This retains the offset-invariant *independent* renewal root, f64 resolution guards, stable obstacle, and prior repairs.
- Donor: PR #4452 HEAD `039d2da975a33a36dcf68a1f13b26b82bb0a74a9`, source blob `e80f667a75a97f722f27438e89e129c8ffa417b9`.
- The resulting primary `regenerative_boundary` function was compared byte-for-byte to donor #4452; all other parts of the destination parent's `stopping.py` were preserved.
- Resulting combined source blob: `84c652048ab7d75d835d48aeafe0285874c4bfa8`.
- Donor wide-transition regression test blob: `3a909c6d774cd980fb0f75b7792cb093f2d4b251` (unchanged).
- No production Rust/GPU, financial HX formulas, learning, NDU, authority, or CI configuration changed.

## Reproduced regression and scoped positive evidence

The `regenerative_boundary` implementation on the destination parent retains the old `h<=1e-4` series switch and lacks the moderate-h Newton correction. In the declared scalar reference, the already-published `h=0.0011940784715932823` witness has approximately `1.10991e-13` relative threshold error against the independent 320-digit Decimal oracle. The wider transition suite demonstrates 53 failed **subtest assertions** on the unchanged local reference function (three test methods); these are not 53 separate jobs.

The composition preserves the h<=1e-3 series branch and the `1e-3<h<=0.1` stable Newton refinement from #4452. Local Linux Python 3.13.5 / SciPy 1.17.0 / mpmath 1.3.0:

```sh
python3 -m unittest -q \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint \
  experiments.hcsn_hx_unified_v3.test_stop_kappa_scale \
  experiments.hcsn_hx_unified_v3.test_independent_smoothfit_gate \
  experiments.hcsn_hx_unified_v3.test_independent_offset_gate \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint_wide_transition
```

**30/30 selected methods PASS, 0 skipped**; measured local process wall ~3.09 s and peak RSS 125964 KiB. The new test file and existing `test_stop_branchpoint`, `test_independent_smoothfit_gate`, and `test_independent_offset_gate` files have remote-identical Git blob hashes in the local test reconstruction. The local `stopping.py` originated in a reduced research reconstruction and is **not** the complete byte-identical destination file. The primary function in the actual committed source was independently compared byte-for-byte with donor #4452, while the rest was preserved from destination #4451. Therefore this is **relevant-function and selected-suite evidence, not whole-repository checkout, full source-exact integration, or passing GitHub Actions**.

## Remaining blockers: do not enlarge the claim

This composition only joins two previously independent scalar P0 numerical repairs. It does not certify finite-precision error intervals, all-parameter He--Xiong coupled financial equilibrium/obstacle, gradient bounds at h->0, full QVI or native low precision. The negative existing P1 0/4 and P5 external comparisons remain binding. No P2 long-memory quality or physical repeated-event training, P3 four genuinely paired modalities, P4 native Rust/GPU, joule, 64/256/1024/4096 Cells or recovery qualification occurred. Do not merge into a production path or promote the architecture based on this scoped diagnostic.
