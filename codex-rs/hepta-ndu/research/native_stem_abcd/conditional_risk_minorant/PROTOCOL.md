# R23 frozen protocol — conditional-risk scalar minorants for the same 2/3/4-width Stem

## Provenance and registration limitations

Exact parent R22 PR #2154 HEAD `575b1121dfdcc9b1089cb9e915d0e0c037f1611d`. R21 protocol/candidates/120 raw fit tensors and R22 positive/negative certificate histories remain untouched. Exploratory sequential follow-up informed by known R21/R22 failures, NOT blinded independent preregistration. Protocol is pushed BEFORE new R23 proof efficacy sweeps; no refits in R23.

## New scientifically independent lower-bound mechanism

The two-step forward law and both positive entropic recursion layers are EXACTLY those of R21/R22: known independent equiprobable x in {-1,+1}, preference p0 in {0,1}, two independent signs e1/e2; gamma=9/10, entropic risks rho0=1/2,rho1=1. h1=a*x+c, h2=b*h1+d*h1²/4+(a-b)²/4+q(a,1/25)+q(a-b,1/8)+e2/10. Missing c,d are identically zero at widths2,3. terminal (h2-x-1)²+p2/50; stage p1/20; L2 weight penalty sum theta²/4, outside risk. No optimizer label, no change in input law.

For each x, all stochastic preference and epsilon branches depend on weights ONLY through one scalar residual r_x=h2_noeps-x-1. Write exact full population cost J(theta)=Phi(r_-)+Phi(r_+)+||theta||²/4, where Phi is a shared positive-risk nested CE function averaged across initial preference states. Phi''(r)>=gamma² globally because the inner CE of squared residual is >=2-strongly convex, positive-risk outer CE preserves convexity, and both gamma factors remain.

For each width n, preselect two rational scalar anchors r_x(theta_n_candidate) from the UNCHANGED R21 candidate. Rigorously bound Phi(anchor) from below and Phi'(anchor) via exact Fraction arithmetic and a certified tanh Lambert continued-fraction interval (R22 source). For each candidate parameter box B, rigorously enclose r_±(B) with exact interval arithmetic, then use the globally valid scalar tangent minorant

Phi(r) >= Phi(r0)+Phi'(r0)*(r-r0)+(gamma²/2)*(r-r0)².

Evaluate the interval product lower and exact interval squared-distance lower for each x; add exact sum theta²/4 lower. For rigor retain max(original R21 lower, R22 centered-gradient lower where specified, new branch/risk minorant). New technique decomposes risks **before** interval extension of parameter dependencies; it is not a global convexity assertion in neural parameters and cannot certify arbitrary unknown-world FBSDE.

## Frozen proof comparisons and budgets

Only the following new cases, each with EXACT 4000 box split limit, SAME R21 rational candidate, root cube [-3,3]^n, same target 0.01 and same float-only heap ordering for search priority:
- `risk`: max(original natural interval, new conditional-risk scalar minorant).
- `risk_centered`: max(original, R22 centered-gradient, new risk minorant).

All n in {2,3,4}: SIX new proof trees and exact root/pruned/frontier logs, under cap. Historic R21/R22 original and centered outcomes are read and independently replayed, not attributed to new experiments or silently rerun at different resources. Primary question is success of 4-parameter certification at 0.01 with fixed cap, and time/RSS cost; secondary is w3. Failure preserves all negative results, no cap enlargement, altered thresholds or retrospectively favorable anchors.

Reclassify all 120 FROZEN R21 final tensors under new global lower bounds and their individual strict rational point upper bounds. All original R21/R22 recorded decisions remain as historical comparators. Original archive and all tensor/checkpoint identities are read-only. New certification IS NOT a training win, a new learned behavior or a global optimal-weights proof.

## Verification and execution

Pre-efficacy derivation tests: exact risk scalar identity against independent full 16-leaf high-precision mpmath, rigorous Phi'' lower and candidate point tangent, derivative bounds against independent mpmath derivatives for perturbations, residual ranges contain direct evaluation, box point/edge/random inclusion tests including negative boxes, and cross-mode never weaker at same BOX. Bind source SHA hashes, six full split/frontier transcripts and per-case rational global gap. Audit every split/child, mathematical prune and cube cover; verify source lineage and all 120 original weights without fits. Include adversarial real-artifact tamper checks under python -O.

Record all six proof CPU/wall and peak RSS and independent audit separately; compare entire proof cost rather than just nodes. No energy/GPU/FLOPs; assistant-container CPU source slice, not user's project cloud, native hardware or full Rust/Bazel CI qualification. Keep Draft, no main merge/CURRENT/production/model authority change; CI result explicitly checked separately.
