# HCSN P0 — fail-closed one-shot cost-translation resolution

**DRAFT / RESEARCH ONLY / DENY_ALL.** `all_blockers_closed=false`; `production_activation_allowed=false`.

## Exact source and scope

Stacked on [#4455](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4455) at immutable HEAD `8a216c3d084680d79f2c491031e83271e1db62c5`. The inspected upstream `stopping.py` blob was `40cd1c47d56ae89d5740aabe45ef33a327856022`; resulting edited source blob `046182ade9fcf888d69ee3947ef83a861987e8b2`. Modify only the scalar one-shot boundary precision admission, add a dedicated test and preserve a reachable immediate-value-overflow test. Financial He–Xiong `hx.py`, renewal root, Rust/GPU, CI, training, authority and deployment are unchanged.

## Actually reproduced numeric false accept

`Stop(0,1,.007,cost,cost-10,0)` has a mathematical one-shot displacement `1/kappa` of approximately `8.451542547285166` for the represented f64 characteristic root. The existing `one_shot_boundary` admitted a finite threshold strictly exceeding cost even when translating it back to the absolute f64 coordinate lost material firing-reward precision.

| cost | previous `b-cost` | displacement (independent 90-digit Decimal with represented input kappa) | relative deviation | ULP(b)/displacement |
|---:|---:|---:|---:|---:|
| 1e8 | 8.451542541385 | 8.451542547285 | 6.98e-10 | 1.76e-9 |
| 1e9 | 8.451542496681 | 8.451542547285 | 5.99e-9 | 1.41e-8 |
| 1e10 | 8.451541900635 | 8.451542547285 | 7.65e-8 | 2.26e-7 |
| 1e12 | 8.451538085938 | 8.451542547285 | 5.28e-7 | 1.44e-5 |
| 1e14 | 8.453125000000 | 8.451542547285 | 1.87e-4 | 1.85e-3 |

Negative cost offsets exhibit the same aliasing; cost = -1e10 has the same observed discrepancy as +1e10. For these inputs, a later high-precision operation cannot recover the already-rounded cost translation.

## Narrow fail-closed correction

Keep both existing conditions (finite displacement; finite threshold strictly greater than cost). Add `math.ulp(b) <= 1e-8 * displacement`, matching the prior research scalar-regenerative boundary resolution policy. Refuse violations with `ArithmeticError`; do not clamp, silently shift boundaries, or treat a refusal as a successful firing event. This is a fixed **engineering precision threshold**, not a guaranteed relative-error bound or rigorous directed-rounding interval certificate.

The previous one-shot overflow regression used a threshold that this stricter guard now correctly rejects. Change only its numerical parameters to `Stop(5e306,1.,.1,-1e308,-1.2e308,0.)`, which has a resolved boundary yet still produces an overflowing immediate `x-cost` at `x=1e308`. Thus the original nonfinite-value refusal remains directly exercised.

## Executed scoped verification

Local Linux/Python 3.13.5, focused transcription of the inspected `Stop.kappa`, `one_shot_boundary` and `one_shot_value` only, **not a source-exact full-repository checkout**:

- Before adding the guard, five new unit-test methods yielded **12 failing subtest assertions** (nonzero exit), including accepted large ±cost and a randomized precision-property violation.
- After adding the guard, **5/5 methods PASS, zero skipped**, including 256 deterministic translated-cost probes, independent 90-digit Decimal comparisons, normal/offset controls and immediate-value overflow refusal; `compileall` PASS.
- Three previously registered one-shot invalid-boundary probes still refuse, and four normal controls across four states (16 observations) preserve expected values.
- All test methods in the committed new test module are adapted from this locally executed focused test; the remote committed full module and full-suite CI have **not** been locally executed. Do not confuse committed test code with green source-exact CI.

Replay from a full checkout of this branch:

```sh
python3 -m unittest -q \
  experiments.hcsn_hx_unified_v3.test_one_shot_resolution \
  experiments.hcsn_hx_unified_v3.test_one_shot_cost_ulp_gate \
  experiments.hcsn_hx_unified_v3.test_oracles
```

## Remaining blockers

P0 still lacks all-domain coupled HX fixed-point/QVI certification, certified quadrature and true fp32/f16 numerical proof. P1 existing negative matched-control evidence remains binding; P2 sampled repeated events and memory, P3 four-modal paired training, P4 Rust/GPU 64–4096 Cell resource/energy/recovery, and P5 fixed-data/token/compute outperformance remain unclosed. This patch grants no production or financial decision authorization.
