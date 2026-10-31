# P2 causal checkpoint: local-ULP subset gate

**DRAFT / research-only / DENY_ALL**; `all_blockers_closed=false`; `production_activation_allowed=false`. Immutable parent is PR #4473 HEAD `ad05317ce62add2658a8a7ba08e316dbf09e6e82`. Only two-state constant-rate CTMC reference, one new focused test and this evidence note change.

## Counterexample

The prior `_killed_masses_are_subsets` used `16*ulp(1.0)` for every state. It admitted `RenewalState(time=0, active=0, no_fire_active=1e-16, no_fire_refractory=1-1e-16, ever_fired=0, expected_count=0)`: the saved checkpoint has exactly unit first-event mass but claims positive unfired-active particles when **no** physical particles are active. It also admitted the symmetric `active=1, no_fire_refractory=1e-16` impossible checkpoint. Both pass `advance(...,dt=0)` in the old parent, so a restart can silently accept invalid causal state.

## Scoped repair

Use a per-comparison allowance `8*max(ulp(physical), ulp(no_fire))`, with `physical=active` for active and `physical=1-active` for refractory. At near-zero population this no longer grants the unrelated absolute `ulp(1)` slack; at ordinary populations it preserves a bounded f64-roundoff allowance. This is a **necessary subset invariant**, not an independent interval-bound proof of CTMC floating-point accuracy. Other broad mass-balance tolerances remain unchanged.

## Independently executed evidence

- Python 3.13.5 / NumPy 2.3.5 / SciPy 1.17.0 / Linux CPU.
- **7/7 focused unittests PASS; 0 skipped**, including 2 forged subset checkpoints rejected, 1-ULP near-0.5 admission, subnormal-scale reachable state checks, **5,000 actual random multistep transitions accepted**, 64 independent `scipy.linalg.expm` comparisons and high-CDF erased-increment refusal.
- `compileall` PASS. The reconstructed unmodified source was verified byte-identical to parent Git blob `fed95910b26e02a0bd0ba7937cb8fd9ddeb5bd06`; tested modified source blob `179e432ea91a2360cea65aaffd3b633ffcac7879`, test blob `8ba50b013636603629b87762e5d96f11f26a6777`.
- Focused command: `PYTHONPATH=. python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_subset_local_ulp_gate`, followed by `python -m compileall -q` for source and test. Full existing parent suites and full-repository checks were **not** executed in this local reconstruction.

## Admission boundaries

Only an invariant/representation check for a memoryless, two-state CTMC is repaired. Not evidence of physical multi-spike neural memory, Selective Copy, MQAR, long-range retrieval, irregular time or regeneration benchmarks. P0 HX/QVI, P1 Call/Risk/Margin attribution, P3 multimodal encoder, P4 native Rust/GPU and P5 matched-budget backbone superiority all remain open. Retain Draft until independent matrix/mass, precision and real-task gates close.
