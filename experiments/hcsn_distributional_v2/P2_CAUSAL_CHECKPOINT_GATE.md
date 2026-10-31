# P2 causal checkpoint subset and representable time — research only

**DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

## Immutable dependency

- Exact parent: draft PR #4447 head `18efb4c8dbff36aa6f4450bd98122115b336aff6`.
- Original oracle Git blob `76cdfeb363e08b052d0634994f67248a9b01f72d`; original eight tests unchanged.
- Changes only the independent two-state renewal oracle and adds a separate test and this gate note. No Rust, authority, GPU, training, CI or deployed neural behavior changes.

## Reproduced original failures

1. The killed/no-previous-FIRE active probability is a **subset** of the unconditional active probability, and killed refractory is a subset of unconditional refractory. Hence `no_fire_active <= active` and `no_fire_refractory <= 1-active` must hold. Unit-mass and nonnegativity checks alone are insufficient. The original accepted `RenewalState(0., .1, .6, .3, .1, 5.)` at zero step, and could emit impossible killed/unconditional populations on a positive step. This patch rejects both invalid persisted and computed states.
2. A reachable checkpoint from `advance(RenewalState.initial(1.), 1e-20, 1., 1e16)` has clock time `1e16`. Applying `lam=gamma=1, dt=.25` previously changed the event probability and expected count while leaving the recorded time exactly `1e16`. The patch refuses positive steps without a representably advanced finite f64 time.

The causal subset comparison permits a small absolute tolerance of `16 * math.ulp(1.0)` for numerical roundoff. This is a diagnostic policy, not a rigorous all-parameter error enclosure. No clipping or fake normalization is used. Zero-duration steps remain idempotent.

## Source-exact executed CPU evidence

- Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, Linux x86_64.
- Original #4447 source/test reconstructed and checked against their Git blob identities.
- Parent with all 13 tests: three expected FAIL (two killed-state subset witnesses, one erased positive time); eight original tests PASS and two new positive tests PASS.
- Patched source: **13/13 PASS, zero skipped**. Includes independent SciPy matrix exponential and quadrature, variable-rate stepping, and cross-interpreter JSON restore.
- `compileall` PASS for changed files.
- Seed 2026103102: 10,000 reachable, seven-step chains; **69,103** jointly accepted updates, **zero output differences** against original. Existing refusals remained refusals.
- Patched source Git blob `d8d8798f193733c6782eb8847af921e69f091ee4`; new test Git blob `4388c6761f9a998567106f4364e785c5a288ae56`. Both exact files were tested locally and matched their remote blobs.

## Reproduction

From repository root:

```bash
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_event_oracle experiments.hcsn_distributional_v2.test_renewal_causal_checkpoint_gate
python -m compileall -q experiments/hcsn_distributional_v2/renewal_event_oracle.py experiments/hcsn_distributional_v2/test_renewal_causal_checkpoint_gate.py
```

## Remaining gates

This tests a bounded memoryless two-state reference, **not** the full physical HCSN or globally valid externally supplied histories. No P0 coupled He–Xiong obstacle, complete P1 causal benefit, P2 Selective Copy/MQAR/overwrite, P3 four-modal generalization, P4 native Rust/GPU power/4096 Cell recovery, or P5 compute-matched backbone advantage is certified. Never use this patch as production activation authorization.
