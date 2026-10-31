# P2 first-fire probability resolution gate: source-integrated research

**RESEARCH ONLY / DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false**

## Scope and immutable dependency

- Exact parent draft PR #4464 HEAD: `1e55a8ba80a6a9269d2cfb08fe46c8390e508528`.
- Existing two-state CTMC source blob: `9dc257423d2dd9ee54ebea2a742552593f7eb997`.
- Edited only `experiments/hcsn_distributional_v2/renewal_event_oracle.py` directly after the event-CDF accumulator, adding a necessary monotonic-resolvability fail-closed test.
- The parent repair to short-step active mass, expected event count and causal checkpoint integrity is preserved verbatim.
- New regression source blob: `b5344911a7d11db91a3979b86e775e32b7200098`; exact locally executed test bytes verified against remote.

## Independently reproduced negative witness

Under constant rates `lam=gamma=1`, start active and run `dt=30`:

- Stored `ever_fired = 0.9999999999999064`.
- Stored first-event survival `no_fire_active = 9.357622968840175e-14`.
- Next `dt=0.0001` has strictly positive first-hit CDF increment `exp(-30) * (1-exp(-0.0001)) ≈ 9.36e-18`, independently evaluated with 100-digit Decimal.
- The inherited finite-precision accumulator rounds the advanced `ever_fired` **to the same number**, while `expected_count` and physical time increase. The previous ~1e-10 absolute mass-balance tolerance is not an error bound proving this path legal.

A high-priority scientific requirement is not to treat this rounding as an actual absence of first hits. When positive killed mass remains, every strictly positive time step under positive rates has a strictly positive first-event increment. If its computed increment is zero, or adding it cannot increase the persisted CDF at f64 resolution, **reject explicitly** rather than silently accepting an inconsistent checkpoint. This does not manufacture sub-ULP probability or alter the stochastic model. A long stream may now refuse earlier; refusal is not success.

## Actually executed checks, scope, and limits

- Executed 5 source-importing Python `unittest` methods locally against the exact **earlier #4450** relevant module (its `event_increment`/`fired` arithmetic is unchanged in #4464): **2 failures before** the new guard; **5/5 PASS, 0 skipped** on a locally modified relevant module.
- An independent 100-digit Decimal first-event increment proved the negative witness is positive and smaller than half a CDF ULP.
- Normal time-step cases, refractory-first, repeated event expectation and exact zero-time identity passed the local focused tests.
- **NOT executed:** complete byte-identical parent #4464 module, full new remote `renewal_event_oracle.py`, all parent regression suites or full repository CI. The exact committed new test file matches the locally executed file by Git blob hash. Do not relabel the reconstructed earlier source as exact #4464 test evidence.

### Required exact-checkout commands

```sh
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_first_cdf_precision_gate
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_count_precision_gate
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_causal_checkpoint_gate
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_event_oracle
```

## Scientific non-claims

This is a two-state constant-rate CTMC precision guard. It is not proof of learned physical repeated spiking, continuous-time first-hitting neural dynamics, unbounded event count exactness, Selective Copy/MQAR or reliable long-stream memory. No change to production owner, Rust, GPU, auth or training. P0 coupled HX/QVI and interval certification, P1 Call/Risk/Margin causal benefit, P2 real task/memory, P3 four-modal quality, P4 native hardware performance/energy/recovery, and P5 matched-budget superiority all remain open.
