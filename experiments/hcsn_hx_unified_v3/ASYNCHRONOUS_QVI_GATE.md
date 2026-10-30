# P0: asynchronous two-cell regenerative QVI — bounded research evidence

**DRAFT / DENY_ALL / NOT PRODUCTION.** This is an additive continuation of #4388 at exact head \`8af5999908e239f02ac17e2c7d7cb711051e50e5\`. No changes to upstream He–Xiong finance kernels, original scalar stopping, prior two-cell solver, previously frozen experiments, Rust authority, training, release or deployment.

## Precise alternative mathematical model

#4388's two-cell QVI freezes **both** neurons for a **deterministic** refractory duration after any firing. This research alternative instead uses **independent exponential** per-neuron refractory times, with mean \`Stop.refractory\` and hazard \`lambda_i = 1 / Stop.refractory\`. This reinterprets the original parameter: the two models are **not equivalent** and no deterministic-delay error bound is claimed.

Each axis has finite active grid coordinates plus one refractory sentinel. A fired neuron receives \`x_i - cost_i\` immediately and moves to its sentinel while the other neuron continues to evolve. During refractory, only the fired neuron's coordinate is frozen at its reset. The other coordinate continues its reflected blocked-outward-jump finite CTMC, can fire, and can undergo its own independent refractory recovery. Upon recovery, a reset coordinate is convex-interpolated between adjacent active grid positions. When a cell is refractory it cannot fire. The full finite-state space has \`(n1+1)(n2+1)\` states.

The **stationary discrete QVI** is

\`\`\`text
max{ (Q-rho*I)V,
     x1-cost1 + V(refractory1, j) - V(i,j) [FIRE1 eligible],
     x2-cost2 + V(i, refractory2) - V(i,j) [FIRE2 eligible] } = 0.
\`\`\`

Immediate firing has no spurious \`exp(-rho*tau)\` factor because the transition consumes no time. At most two firings can occur without a WAIT, since firing strictly increases the number of refractory cells. All returns to active status require stochastic positive-time recovery under positive discount. Finite positive generator rates and recoveries make the finite-state policies proper in exact arithmetic. A numerical guard rejects cases where floating-point summation erases the discount from a WAIT row.

This is not the original HX corporate credit fixed point and not a true continuum SDE, deterministic refractory implementation, or a training-ready neural layer.

## Locally executed validation

Environment: Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0; CPU only.

\`\`\`sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_asynchronous_qvi
python -m unittest -v experiments.hcsn_hx_unified_v3.test_coupled_qvi experiments.hcsn_hx_unified_v3.test_asynchronous_qvi
\`\`\`

**24/24 combined upstream+new tests passed** against byte-exact #4388 source; 12 new methods. This is a bounded local result; it is not a full-repository CI or a product gate.

- Howard sparse policy evaluation versus Jacobi value iteration (different algorithms, **same discrete finite-state model**) agree to <1.5e-8 in four prescribed parameter configurations including drift-dominated upwind cases. Independent scalar-loop generator and obstacle residuals pass.
- 32 seeded finite-admissible configurations on 9×9 active grids pass independent scalar-loop residual <2e-8; **not** an all-domain guarantee.
- One-cell-inert case agrees with a separately programmed scalar exponential-refractory oracle. Both cells inert => value zero. Swapping cells preserves the value; symmetric parameters preserve symmetry.
- Refractory1+active2 and active1+refractory2 states demonstrate that the other cell continues to move and can FIRE while the first is refractory. A near-zero-diffusion toy example permits two distinct immediate firing events without false global freezing.
- Four seeded CTMC Gillespie starts, 1000 simulated trajectories per start, agree with fixed-policy computed values within 5.5 standard errors plus 0.025; this is a **statistical** check, not a proof.
- For one selected domain and parameters, values at active state (0.5,0.5) on 9²,17²,33²,65² active grids: 0.3614099463630203, 0.34132849696135514, 0.3352685778988326, 0.33368622272518433. Not a continuum error bound.
- Maximum |asynchronous-exp-refractory value − global-frozen-deterministic value| is 0.22786811456783074 on one selected 13×13 grid. This **must not** be interpreted as the causal effect of asynchronous updates alone, since the refractory-time distributions also change.
- Malformed input, extreme-rate discount loss, improper budgets and solver exhaustion fail closed.

## Still blocked: no promotion of P0–P5

1. Full HX financial fixed-point existence/admissibility, complete parameter domain, derivatives/interval error bounds and singular limits remain OPEN.
2. An implementation of **independent deterministic** refractory periods with independent time-flow, timing accuracy, multiple events, numerical robustness, and gradient evidence remains OPEN. This model assumes exponential waiting and a finite grid.
3. No certified continuum limit; no long-horizon selective-copy/MQAR/rewrite pass; no P1 matched Call/Risk/Margin performance advantage. Existing negative ablations are unchanged.
4. No real four-modality encoder, no native Rust/GPU production system, no 64/256/1024/4096 Cell hardware costs/energy/fault recovery, and no P5 equal-budget backbone superiority.
5. State space is a tensor product; this two-cell model is **not** scalable by direct extension to thousands of cells.

The only safe conclusion is that an *explicitly defined finite-state asynchronous competitor* has a numerical reference and adversarial checks. Keep all HX/CSN production admission gates **DENY_ALL**.