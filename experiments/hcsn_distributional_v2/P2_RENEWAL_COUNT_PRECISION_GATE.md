# P2 constant-rate renewal count precision gate

**DRAFT / research only / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

Parent is #4450 exact HEAD `5630560c3855c7f9ae79f89557b57961bbb1addf`. Only the offline two-state CTMC reference plus one independent regression and this note are modified. No learning, source corpus, original HX financial formula, native production Rust/GPU, CI or authority changes.

## Two verified failure modes

**Tiny refractory steps.** Starting entirely refractory with `lambda=gamma=1`, the true expected count for a positive step is `0.5*(dt-(1-exp(-2*dt))/2) ~ 0.5*dt^2`. The inherited occupation formula `eq*dt+(active-eq)*(-expm1(-s*dt))/s` subtracts two nearly equal O(dt) terms. In local Python 3.13/SciPy numeric probes, at `dt=1e-17` and `1e-20` it returned **zero**, while independent 120-digit Decimal integration gives about `5e-35` and `5e-41`. At `dt=1e-16` it had about 23% relative error.

**Erased checkpointed count.** The reachable `advance(initial(active=1),1,1,1e16)` checkpoint has `time=1e16` and `expected_count=5e15` (one count ULP = 1). A next `lambda=gamma=.001,dt=2` increases physical time representably and implies a **positive expected count increment 0.001**, but the inherited `fsum(5e15,.001)` stays `5e15` without refusal.

## Repair

For `(lambda+gamma)*dt<=0.05`, integrate active occupation as a sum of **nonnegative** terms:
`occupation=active*J+(gamma/s)*D`; `J=int_0^dt exp(-s*u)du`; `D=dt-J=dt*(x/2-x^2/6+x^3/24-...)`, `x=s*dt`. A bounded alternating series evaluates `D` without subtracting two O(dt) quantities. The regular-rate branch is unchanged. Additionally refuse positive steps with an unrepresentable nonpositive event-count increment or an increment erased at the persisted f64 count scale; never clamp or credit a fictional event.

Independent local Python tests of the replacement integration expression matched 120-digit Decimal results down to `dt=1e-20`, and reproduced the large-count alias/refusal. This session **did not run full exact-source repository integration or CI**. Five source-importing `unittest` regression methods are committed for that independent verification:

```sh
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_count_precision_gate
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_event_oracle
python -m unittest -v experiments.hcsn_distributional_v2.test_renewal_causal_checkpoint_gate
```

## Boundaries

This is a constant-rate two-state CTMC and **not** an actual learnable HCSN, genuine Selective Copy/MQAR/long-memory benchmark, stochastic threshold crossing, complete P2 or production admission. No power, energy, throughput, multi-modal encoder, or downstream Net Utility claims. P0–P5 remain open.
