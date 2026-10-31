# P2 independent repeated-event renewal oracle — research only

**DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

Parent: #4439 exact HEAD `3cbe89d976cd398c5344ee7588dde6c88ef2984d`. This is an *additive* two-state analytic reference, not a modification of the trained HCSN, previous `stable_probability.py`, frozen task results, Rust owner, GPU, CI or production behavior.

## Reference problem

The active phase has an exponential firing hazard `lam>0`; after FIRE it enters a refractory phase, from which it recovers at rate `gamma>0`. The physical two-state row generator is

```
Q  = [[-lam, lam], [gamma, -gamma]]
Q0 = [[-lam, 0],   [gamma, -gamma]]
```

`Q0` is **killed at the first FIRE** and is necessarily substochastic. The full chain can FIRE repeatedly, and its expected count is the integral of active occupancy times `lam`.

The oracle independently retains:
- unconditional active/refractory probability;
- *unnormalized* no-previous-FIRE active/refractory probability;
- probability of at least one FIRE;
- cumulative expected FIRE count;
- elapsed time and explicit checkpoint version.

Crucial counterexample: at `lam=8`, `gamma=10`, `T=3`, the expected event count is greater than **10**, while at-least-one event probability is at most **1**. A first-fire probability can never substitute for total regenerative event count. The no-event channel must not be renormalized into a unit-mass transition.

## Executed evidence

- Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0 on Linux CPU.
- Eight new tests **8/8 PASS, zero skipped**; source/test compileall PASS.
- 64 seeded independent `scipy.linalg.expm` full/first-killed generator comparisons plus independently integrated active occupation/reward.
- Nonuniform time segmentation vs single segment; piecewise rate changes vs ordered matrix exponentials; near-coincident rates; small-time refractory first-arrival quadratic law; invalid numeric states and checkpoint version refusal.
- Versioned JSON numeric state restored in a **new Python interpreter** reproduces the suffix exactly for the specified case. This does not claim independent-process neural-state or power-failure restoration.
- Additional 2,048 seeded rate/time/stiffness probes: **2,048 accepted / 0 refused**; maximum absolute discrepancy against independent SciPy `expm` result across the tested state/first-event fields ~**1.65e-11**. This is an observed finite-domain diagnostic, not an interval-certified bound.

Reproduce from repo root:

```bash
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_event_oracle
python -m compileall -q experiments/hcsn_distributional_v2/renewal_event_oracle.py experiments/hcsn_distributional_v2/test_renewal_event_oracle.py
```

Exact source/test Git blobs, matched after publishing:
- `renewal_event_oracle.py`: `76cdfeb363e08b052d0634994f67248a9b01f72d`
- `test_renewal_event_oracle.py`: `b862c14228c0e3ae3a74f3e4bf9e31ab48568ba7`

## Scope / remaining blockers

This is a two-state memoryless CTMC **reference**, not the HX endogenous boundary, no Erlang/fixed refractory, no trained content memory, no real sampled hardware spike trace and no genuine neural long-range retrieval. The underlying trained finite HCSN implementation is not altered or validated by direct A/B source integration here.

**P0:** coupled HX financial obstacle/FP32/implicit gradients remain incomplete.
**P1:** previous 0/4 positive mechanism gates remain negative; matched heldout gain is absent.
**P2:** Selective Copy/MQAR/overwrite, variable physical event trajectories, real non-Markov renewal, checkpoint/owner recovery must still be shown.
**P3:** four-modal pairings/OOD absent.
**P4:** no rustc/cargo in current local container; **no native Rust/GPU/energy claims**, no 64–4096 Cell production evidence.
**P5:** no matched quality-conditioned, full-cost Transformer/SSM and shared-Encoder comparison.

No production qualification or deployment is authorized by this exploratory oracle.
