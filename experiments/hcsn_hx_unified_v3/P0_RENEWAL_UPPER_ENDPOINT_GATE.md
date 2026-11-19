# P0 upper-endpoint Lambert-W renewal admission — research gate

**DRAFT · DENY_ALL · all_blockers_closed=false · production_activation_allowed=false**

## Immutable parent and scope

Parent is draft #4460 HEAD `dac62e04795b4f77e0f7c9089d5fa1462ecf86a3`, stacked over the earlier #4455/#4456 fixes. This patch changes only the research stopping reference plus adds one local regression and this evidence note. It does not modify finance HX formulas, any controller/training, native Rust/GPU, production authority, or CI settings.

## Reproduced false acceptance

For `Stop(drift=0,diffusion=1,discount=.5,cost=0,reset=-h,refractory=0)`, the positive characteristic root is `kappa=1`, and the scalar renewal displacement is `t=1+W0(-exp(-h)/e)`. Every **finite** `h>0` has a *strict* `0<t<1`, with `1-t=exp(-h-t)>0`. In IEEE-754 binary64, the previous primary path instead yielded `t==1` for `h=37,40,50,100,710` and returned the exact one-shot boundary `b=1` as a solved finite-renewal threshold. The inherited independent root already rejects these cases.

A separate local SciPy reproducer confirmed all five silent primary admissions. A 150-digit Decimal fixed-point calculation for `s=1-t` proves that the interior root has a positive, sub-half-ULP gap at `h=37,40,50,100`: no distinct binary64 interior `t` exists there.

## Narrow repair and evidence limits

After the legacy series/Newton/Lambert path, require `math.isfinite(t) and 0<t<1` before forming `b`. This rejects upper-endpoint saturation rather than falsely relabeling the one-shot limit as the strictly interior renewal optimum. No arbitrary threshold is introduced; no value is clamped.

Three independent, **expression-level** local Python/SciPy test methods passed (5 saturation probes, four high-precision probes, and ordinary-range preservation). Four new **source-integrating** `unittest` methods are committed but were **not executed against the full exact repository checkout** in this session. That work and repository/CI integration remain to be independently verified.

Suggested checkout reproduction:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_renewal_upper_endpoint_gate
python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles
```

The patch is a **negative safety admission**, not a certified root interval, all-parameter guarantee, completed HX coupled obstacle, positive P1 causal experiment, P2/P3 learning outcome, native P4 GPU scale result or P5 backbone-superiority result. All P0–P5 blockers stay OPEN. Never merge as production-ready or activate on the basis of this gate.
