# Two exact equity/default means can hide a 37.3-point change in the next event probability

With stationary parameters and a single positive surviving state, its one-year first-hit probability is strictly decreasing in asset V above the boundary. Coupling two paths to the same Brownian increments preserves their separation and gives a positive probability of the lower path hitting before the higher one. Hence an interior F uniquely determines V and the analytical equity E(V) when parameters are public. Two outputs are different nonlinear readouts of this one coordinate. A population average changes the question because E and F are nonlinear.

Consider two probability populations on 513 present-state levels. Both send the same mean analytical equity (11.7511743) and the same mean one-year un-discounted default probability (.54521906), with the same present boundary 67.441515. After an unanticipated common shift to intensity four, their genuine quarter-year first-hit probabilities are .875766 and .502767. The maximum difference is .372999, and the two messages also match byte-for-byte when stored as two FP32 values. An 8-byte sender restricted to these two specific averages therefore cannot provide every future event probability. This is not a bound for an arbitrary encoder using eight bytes.

For distributions supported *strictly* in the continuation region, removing the contact point gives a .371033 gap. Requiring all states to exceed the current boundary by at least 1 or 3 monetary units leaves .344646 and .272250. These sensitivities remove the possibility that the main result rests solely on including an already-contacted atom. The populations are arbitrary mixtures, so the bound need not be achieved under a specific neural state initialization and reset process.

To prove sharpness, arrange the shared instruments and constant column in A and an alternate future probability at each state in q. The primal maximum qᵀ(p−r) over two probability vectors with Aᵀ(p−r)=0 equals twice the minimal uniform approximation error min_c ||q−Ac||∞. One inequality follows from ||p−r||₁≤2; for equality the dual of the uniform-approximation problem supplies a zero-total-mass signed vector with L1 norm at most one. Twice its positive and negative parts give subprobabilities of equal mass, which can be padded by the same distribution. Both primal witness populations and dual coefficients were solved independently and archived.

| Shared mean readings | worst newly revealed intensity-4 quarter-year gap (513 levels) |
|---|---:|
|E, F|.372999|
|E, G (discounted hitting mass)|.379956|
|E, F, G|.178627|
|E, F, log distance|.150538|
|E, F, prior quarter-year F|.214611|

The primary sharp gaps at 129, 257 and 513 levels were .368750, .370548 and .372999. All 180 finite problems produced byte-identical FP32 instrument means across the paired witnesses. Maximum absolute primal–dual discrepancy was 1.48e−11. The no-switch one-year query lies in the span when F is among the messages, giving zero up to solver tolerance. The paper's discounted equity and the finite-horizon discounted hitting mass answer different valuation questions; G is explicitly a discounted first-hit claim here. Reconstruct with sharp.py and inspect witnesses.zip or strict_interior.json.
