# Independent parameter-space stress after the kernel freeze

**All 128 new parameter points passed the registered FP64 and mixed32 numerical
checks.** Every point was locally admissible in both modes, so rejected points
were 0/128 rather than being silently dropped. This is a finite numerical sample,
not a uniform result for the complete nine-dimensional parameter box.

`STRESS_PROTOCOL.json` contains the complete 128-point Latin-hypercube sample,
seed `2026103111`, parameter bounds, fixed error gates and hashes of the frozen
kernel/reference. It was saved before evaluation. No kernel changes were made
after inspecting the stress results. The protocol SHA-256 is
`c651c8df1da469ad9a29c09146883311946748ae76a7a241500b61ac224fd7a4`.

The four states for each parameter point are log-distance `1e-8`, the midpoint
of the new blend interval, log-distance `2`, and an asset value selected once as
`V=initial_boundary*exp(.2)`. For the last state, V stays fixed during parameter
differentiation, so the endogenous boundary contributes its full chain rule.
All outputs and all nine parameter/state derivatives are compared to the
80-digit literal A5/A7 reference, including the independent step-halving check.

| Mode | Admitted / proposed points | Passed / measured rows | Maximum scaled value error | Maximum scaled Jacobian error |
| --- | ---: | ---: | ---: | ---: |
| FP64 | 128 / 128 | 512 / 512 | 1.380e-13 | 5.172e-10 |
| Mixed32, complete FP64 internal kernel | 128 / 128 | 512 / 512 | 5.832e-8 | 5.825e-8 |

The maximum scaled change when halving the high-precision difference step is
below `7.41e-61`. The gates are unchanged from the fixed-fixture study:
FP64 value `2e-8`, mixed-interface value `8e-7`, and Jacobian `2e-5`.
The denominator is `max(1, abs(reference))`, so these do not establish relative
accuracy for arbitrarily tiny tail probabilities.

A separately labeled post-hoc diagnostic found no negative equity/debt or
violations of `0 <= G <= F <= 1` at the sampled states. This does not replace a
global stopping inequality or add a new optimized admission criterion.

`STRESS_SUMMARY.json` is compact. Complete admission records, exact represented
inputs, actual/reference values, full Jacobians, per-row errors and rejection
reasons are the lossless member `STRESS_RESULTS.json` in
`STRESS_EVIDENCE_ARCHIVE.json`. Read it with:

```bash
python -B tools/hcsn/calibrated_operator_r11_20261031/numerics/package_evidence.py --index STRESS_EVIDENCE_ARCHIVE.json --restore /tmp/full-hx-stress-restored
```

This extra matrix provides evidence about previously untested combinations.
Internal FP32 is still unqualified, the excluded extreme limits remain excluded,
and full-HX downstream recurrent task training remains separate from this study.
