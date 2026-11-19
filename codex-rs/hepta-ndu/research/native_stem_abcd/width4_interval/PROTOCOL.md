# R21 frozen protocol — 2/3/4 genuine shared forward weights with direct global interval certification

Parent R20 Draft PR #2112 at exact HEAD `3b1c47979cb7323415275bd84e50547711f1218c`. This is exploratory sequential research. Deterministic **non-efficacy** pilot numerical root solves preceded freezing and supplied the exact 15-decimal candidate coordinates below. They are NOT mathematical optimality proof. Source and protocol must be pushed before the 120-case fresh-process efficacy sweep. Historical source, selected models, CURRENT and production gates remain unchanged.

## Same population, task, physical states and true two-step forward dynamics

X∈{-1,+1}, P0∈{0,1}, e1,e2∈{-1,+1} independently equiprobable, 16 fully enumerated leaves. Preference flips P1=P0 xor [e1=+1], P2=P1 xor [e2=+1]. Two nested positive entropic CEs with rho0=1/2, rho1=1 and discount gamma=9/10; stage P1/20, terminal `(H2-X-1)^2+P2/50`. Penalize sum of trainable weight squares/4 OUTSIDE nested risks, applying the same coefficient per weight.

Three actual **forward** architectures (no pretrained encoder, labels or learned readout):

- W2: H1=a X; H2=b H1 + (a-b)^2/4 + a/[25(1+a²)] + (a-b)/[8(1+(a-b)²)] + e2/10. Exact R20 signed-architecture control.
- W3: H1=a X+c; same H2 as W2. A learned state bias **feeds the second-stage state**, genuinely influencing both steps.
- W4: H1=a X+c; H2=b H1+d H1²/4+(a-b)^2/4+a/[25(1+a²)]+(a-b)/[8(1+(a-b)²)]+e2/10. The added learned mixing coefficient d nonlinearly couples to all of a,b,c.

These have 2,3,4 trainable parameters, not a physical-state or task scaling claim. Stage1 preference transitions remain fixed; e1 changes P1 but not H1. All groups use identical original R20 eight initial (a,b) pairs `(0,0),(.1,.1),(-.1,-.1),(1,1),(-1,-1),(2,-2),(1,-1),(2,2)`; any newly introduced parameter initialized to **zero**. Thus paired groups agree exactly on their shared coordinates and all controls within each width/seed start byte-identically.

## Fixed certification before efficacy

Pre-explored rational decimal candidates (passed as *literal rational numbers*, not as float evidence):

- W2 (a,b)=(1.546968894170478,0.448874006060473).
- W3 (a,b,c)=(0.724272383498535,1.076854103128394,0.727904342674089).
- W4 (a,b,c,d)=(0.766767953723746,0.924372831675018,0.754668981051615,0.360581962736983).

For each width, create exact Fraction box arithmetic propagated THROUGH H1/H2, rational q intervals, squared terminal residuals and **both nested** CE layers via globally valid `logcosh(z) >= max(0,z²/2-z⁴/12)` and `<=z²/2`. No gradient, Hessian, presumed convexity, R18/R19 auxiliary convex quotient, or SciPy result is required for global lower bounds. Minimize over [-3,3]^n using branch-and-bound: bisect longest parameter interval, prioritize by float only (proof comparisons Fraction), stop if the candidate's rigorous upper bound minus all-box lower bound <=1/100, or after exactly **4,000 splits per width**. Predefined progress checkpoints at node counts 0,100,500,1000,2000,4000, plus the actual successful early stop. Outside [-3,3]^n, regularizer alone >=9/4, and independently prove candidate upper cost <9/4. Prune boxes only if their rational lower bound already >= certified candidate upper. Emit the entire unpruned exact-rational frontier and digest it. IMPORTANT: if W3/W4 fail the threshold within cap, report certified remaining gap, no posthoc cap increase, fallback or false success.

The true cost of this *fixed* literal candidate has a strict certificate, regardless of B&B failure; a B&B global regret bound never proves unique minimizing weights. A width-to-width comparison of different finite-dimensional families needs a common law and quality accounting, not direct comparison of parameter-distance labels.

## Frozen efficacy experiment and independent audit

Full factorial 3 widths x8 shared seeds x5 methods =120 fresh subprocess fits: Adam(lr .03), BFGS, L-BFGS-B, trust-exact with manually propagated forward derivatives, and ordinary Torch-AD trust-exact. Fixed CPU process-fit cap .75 seconds, including solver graph work; full imports/serialization and audit metered separately. Solver callbacks capture accepted weights and complete cost checkpoints, without reference optimum or certificate training labels. All runs retained, no retry/suppressed negative cases, prefit plan/source/seals recorded. Success primary: **candidate-independent** certified cost upper bound for the final model relative to the common B&B lower bound <=.01, where finite float64 final weights are treated as exact dyadic rationals and recomputed as exact one-point interval costs. If the **actual final candidate** upper minus the common exact global lower exceeds the threshold, that candidate is not certified, regardless of the pilot candidate's gap; report all endpoint costs, gradients and Hessians even when zero endpoints qualify. The pilot candidate's failure alone is not a proof that no other weight could pass. Preserve 120 complete scores, success/miss and time censoring.

Recompute analytic gradients/Hessians against Torch AD and finite differences on all widths; pure-Python separately enumerate all 16 leaves. Audit every checkpoint, initial & final tensor, accepted updates, source hash, all B&B frontier boxes, root-domain coverage/splits and manuscript claims. Reject tampering including missing census, altered source, rehashed weights/checkpoint costs and false certificate values. CPU/wall/RSS plus cost of global certification are part of complete research accounting, not fitted time-to-quality. Complete FLOPs, energy and GPU numbers unavailable. Runs in assistant CPU source slice, **not** on project cloud, native Neuron or full Rust/Bazel suite. No main merge, native/CURRENT change or general high-dimensional FBSDE/LLM result.
