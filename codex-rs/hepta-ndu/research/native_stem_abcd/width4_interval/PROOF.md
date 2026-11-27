# R21 — rigorously bounded direct nonconvex interval-search of 2/3/4 forward weights

## Same fully known population and genuinely coupled weights

The four independent equiprobable variables X in {-1,1}, P0 in {0,1}, e1/e2 in {-1,1} determine exactly 16 terminal leaves. P1/P2 flip on positive e1/e2. The forward Stem families are

- W2 H1=aX, H2=b H1 + (a-b)^2/4+a/[25(1+a^2)]+(a-b)/[8(1+(a-b)^2)]+e2/10;
- W3 H1=aX+c, same H2;
- W4 H1=aX+c and additionally d H1^2/4 enters H2.

Terminal target is X+1, terminal loss (H2-X-1)^2+P2/50; stage loss P1/20. Each stage uses its observed preference-specific rho0=1/2 or rho1=1 entropic certainty equivalent, gamma=9/10 per recursion. Parameter penalty sum theta_i^2/4 sits outside entropic risk. Third and fourth weights genuinely alter the second-stage state, and the same input/task/distribution are used for all three widths. This is not a readout-only or physical-state scaling.

## Direct exact rational global enclosure

For any parameter box B=product [l_i,u_i], let h1(B)=x a(B)+c(B). The bH1, dH1^2/4, signed rational channels and additional eps2 are enclosed using interval multiplication; squaring intervals accounts for zero crossing. The extrema of q_k(v)=kv/(1+v^2), k>=0, on a finite interval occur among the endpoints and any contained +/-1, so these bounds are exact rational. Every terminal loss has exact rational lower and upper interval bounds.

For any rho>0, CE_rho(y0,y1)=(y0+y1)/2+(1/rho)logcosh(rho(y1-y0)/2). The inequalities

max(0,z^2/2-z^4/12) <= logcosh(z) <= z^2/2

hold for every real z. In particular, the lower inequality follows by integrating tanh(s)>=(s-s^3/3) and logcosh(z)>=0; the upper follows tanh(s)<=s. Both lower and upper CE are monotone in each input, so independently substituting leaf lower/upper values and using these entire-real-line logcosh bounds produces VALID lower/upper bounds for both nested risk recursions. Summing positive-risk states, averaging the known population and adding exact separable weight-square ranges yields certified J_L(B)<=min_{theta in B}J(theta) and J_U(B)>=max_{theta in B}J(theta).

Outside [-3,3]^n, one coordinate has absolute value >=3; the nonnegative stage and terminal costs and positive-risk monotonicity show J(theta)>=sum(theta_i^2)/4>=9/4. Each preselected literal rational candidate has a rigorously computed global cost upper bound <9/4, so the unbounded complement cannot contain a better solution.

The proof-covered root [-3,3]^n is split on the longest side into two disjoint closed child boxes sharing a face. Exact rational lower bounds are computed for both. Boxes whose lower bound >= the candidate's certified upper bound are safely discarded. The complete split trace plus unpruned frontier exactly covers all remaining possibilities. Float priority values in the heap influence ONLY which box gets split next, never pruning or the stopping predicate. A certified global regret upper bound is

max(0, J_U(candidate) - min(J_L(candidate),min_{B in frontier}J_L(B))).

A successful stop is permitted only when this exact Fraction expression <=1/100, or the fixed 4,000-node cap is exhausted. The full tree, frontier, node counts and digests are delivered; a separate read-only implementation replays every split, bound and proof partition.

## Exact outcome and missing certificate

W2: 2,985 splits, exact gap about .00999390815023 <=.01; VALID certification for this fixed candidate. W3: 4,000 splits, exact gap about .04560924840912 >.01; NO .01 certificate. W4: 4,000 splits, exact gap about .13207665196852 >.01; NO .01 certificate. Stronger empirical candidates after fitting yield smaller numerical costs (W3 .65186675655 and W4 .62732409925), but their best per-candidate rigorous gap under the FIXED unchanged global lower bound still exceeds .01 (about .03047556 and .12593658). These are certification LIMITS, not proofs of low-quality models or nonexistence of better parameters.

The arbitrary-precision proof makes no global convexity assumption and no claim about uniqueness or locations of global minimizers. The certificates are for this finite-state, two-step, 2/3/4-weight toy system only. General neural architectures, unknown physical dynamics, continuous state laws and large LLMs remain outside the proved class. The 120 local fit endpoints and all gradient/Hessian numbers are floating computations, not globally exact optimizers. No production authority is conferred.
