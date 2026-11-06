# Exact finite deadline risk/resource frontiers: proof and internal review

Date: 2026-11-06. Scope: finite known catalog, finite **observable** history tree, randomized history policies, and declared duration/censoring laws. This closes a bounded attainability question left open by the prior necessary KL/state-occupancy relaxation. It does not establish an original LP method, an original RL framework, unrestricted unknown-kernel guarantees, measured tool latency, or external mathematical review.

## 1. What is different from the prior reference

The previous `ndu_finite_catalog_20261106/DECISION_COST_THEORY.md` proves a necessary time-expanded state-flow/KL lower bound and explicitly says its feasible occupancies need not be implementable by one common policy across catalog members. Its matching sequential test is unlimited-time, pointwise asymptotic, and regenerative. The construction below instead represents one policy on the actual observed history tree; it gives necessary **and sufficient** finite deadline attainability inside that supplied finite model. This is a computational reference for future learned policies and excludes clairvoyant per-model policy selection.

## 2. Observable tree and cancellation contract

Let `h` range over a finite catalog `H`. The externally fixed correct terminal answer is `a*(h)`. At each decision node `v`, its full observed history specifies elapsed time, prior queries, returned responses/failures, observed states, and paid resources. A legal action is either a terminal decision `STOP(a)` or a query with a selected cancellation cap. Every query outcome `o` creates a child `vo`; the known conditional probability is `p_h(o|v,q)`. The outcomes sum to one for every legal query and every catalog member.

Positive duration, a positive minimum duration, a finite deadline and finite action/outcome alphabets imply a finite tree. Alternatively an explicit finite query limit suffices. Continuous clocks require a genuinely finite observed interface or an explicitly bounded discretization; the theorem does not make an unbounded or continuous observation tree finite by renaming time.

For a cap `b`, completion at duration `d<=b` is observed, and all unavailable events with `d>b` are pushed into the actually observable cancellation event. Their probabilities are **summed before** filtering. If the physical state changes before cancellation, the outcome must record the available cancellation state rather than the eventual state. Fees apply at launch even on timeout. There are no background completions unless the tree explicitly represents them. Clock, legal actions and cancellation mapping are the same across catalog members given the same observable history; they may not depend on unobserved `h`.

All leaves terminate by the declared hard deadline. Hard realized-cost budgets must also be enforced through legal histories/actions. An expected-cost constraint in an LP is not a hard realized-cost guarantee.

## 3. Realization weights

For each node/action pair introduce `x(v,a)>=0`. It is the product of **policy probabilities only** along the action sequence ending in `(v,a)`. It excludes all environment probabilities.

At the root `r`,

`sum_a x(r,a)=1`.

For each observation child `w=vo` of a query `(v,q)`,

`sum_a x(w,a)=x(v,q)`.

Every separate observation child has this equality. The sum across all observation children generally exceeds `x(v,q)`; treating it as conservation of environmental probability is incorrect. Collect these equations as `A x=b`. Inductively every coordinate satisfies `0<=x(v,a)<=1`.

Let `ell_h(v)` be the product of environmental conditional probabilities along the unique history to `v`, with `ell_h(r)=1`. It includes queried outcome probabilities and excludes policy probabilities. Under a behavioral policy represented by `x`, the probability of executing `(v,a)` under `h` is exactly `ell_h(v) x(v,a)`.

### Theorem 1: exact equivalence

The nonnegative solutions of `A x=b` and the randomized observable-history policies have exactly the same attainable terminal error probabilities and expected finite path scores, simultaneously for every catalog member.

**Policy to weights.** Given a behavioral policy `pi(a|v)`, set the root coordinates to `pi(a|r)`; set each descendant coordinate to its predecessor query realization weight times `pi(a|v)`. This gives every flow equality. Multiplication of policy and nature factors gives the execution probability formula by induction. Any policy using an independent persistent random seed has an outcome-equivalent behavioral representation: conditioning on a complete observable history, the nature likelihood is fixed by its action/observation sequence and cancels from the conditional distribution of the independent seed. Full recall is essential to this argument.

**Weights to policy.** Set `m(r)=1`; for a nonroot `v`, set `m(v)` to the coordinate of its preceding query. If `m(v)>0`, define `pi(a|v)=x(v,a)/m(v)`. If `m(v)=0`, choose any declared legal fallback distribution. The flow equation makes these distributions normalized. At a zero-mass node nonnegativity forces all its action coordinates to zero. Induction reproduces every original coordinate and hence every terminal/action probability under each `h`. Randomized terminal decisions are permitted. Terminal normalization follows by summing child likelihoods, using `sum_o p_h(o|v,q)=1`, and recursively replacing queries by their descendants. Thus all leaf masses sum to one under every catalog member. ∎

The result is over policies with the full observation history, not a compressed state that omits information needed to choose future queries. Two catalog members sharing the same correct answer need not have the same optimal information-acquisition policy; their nuisance coordinates can affect query reliability, duration or cost.

## 4. Risk and resources are linear

For each `h`, define the row `E_h` by

`E_h x = sum_(v,STOP(a)) ell_h(v) x(v,STOP(a)) 1{a != a*(h)}`.

The same formula handles any bounded external terminal loss. A known launch fee `f(v,q)` contributes `ell_h(v) f(v,q) x(v,q)`. An outcome-dependent additional fee/duration `g(v,q,o)` contributes

`ell_h(v) [sum_o p_h(o|v,q) g(v,q,o)] x(v,q)`.

Their sum is a resource row `C_h x`. Equivalently a complete bounded terminal path bill can be assigned to leaves; the two accounting routes must agree and must not both be charged. If total score discounts rewards/fees, apply `exp(-rho*t)` at their respective **absolute observed times**, not at the query count; these remain known linear coefficients. Model-supplied durations remain model-time evidence until replaced by qualified metering.

The worst-case expected-resource minimax problem is

`min eta`

subject to `A x=b`, `x>=0`, `E_h x<=eta` for every `h`, and `C_h x<=B_h` for every `h`.

More resource types add rows. A prior-average resource constraint uses its stated weighted row instead; it is a different contract. By Theorem 1, feasibility at `eta=delta` is equivalent to existence of an implementable uniformly `delta`-correct policy meeting exactly these expected-resource and hard-tree constraints. Always-STOP makes the unconstrained-resource risk problem feasible; infeasibility with a stringent error/resource cap is a substantive conclusion.

For finite rational model inputs, this is a finite rational LP and admits rational optimal solutions when feasible. It can be exponentially large in the query horizon because the history tree is large. The sequence-form reduction does not establish polynomial complexity in a succinct POMDP input.

## 5. Dual and certificates

Using `eta` as a free variable, the dual to the minimax LP is

`max b^T y - B^T mu`

subject to `A^T y <= E^T lambda + C^T mu`, `lambda>=0`, `mu>=0`, and `sum_h lambda_h=1`; `y` is unrestricted. A free `eta` causes no problem because nonnegative risk constraints force its optimum nonnegative. If an implementation instead constrains `eta>=0`, the direct dual has `sum lambda<=1`, so the output must state the convention.

For any feasible policy and dual point, weighted risk and the primal equations give `max_h E_h x >= b^T y-B^T mu`. Finite-dimensional LP duality yields equality at an optimum. An exact rational primal/dual pair with zero gap therefore certifies the finite-model frontier. Floating solver success, feasibility residuals and a small gap provide numerical verification; they are not exact rational certificates.

A useful rigorous repair for an approximate dual is possible. Convert its numbers to exact rationals, make `lambda,mu` nonnegative, normalize `lambda` to sum one, and let

`r_j=max(0,(A^T y-E^T lambda-C^T mu)_j)`.

Since every realization coordinate is at most one, the exact scalar

`b^T y-B^T mu-sum_j r_j`

is still a valid lower bound. This may be loose on large trees, but it does not pretend an approximate dual is feasible. An upper bound requires an actually valid recovered policy and exact or outward-rounded evaluation of all resource constraints. If repaired rounding violates a budget, do not label it feasible merely because the violation is small.

### Independent Bellman lower certificate used by the implementation

The implementation need not trust a numerically proposed equality dual `y`. For any rational probability vector `lambda` on catalog members and nonnegative resource prices `mu`, compute by exact backward induction

`F(lambda,mu)=min_pi sum_h lambda_h error_h(pi)+sum_h mu_h cost_h(pi)`.

At terminal action `(v,STOP(a))`, use `sum_h lambda_h ell_h(v) 1{a!=a*(h)}`. At query action `(v,q)`, use `sum_h mu_h ell_h(v) E_h[charge|v,q]` plus the sum of child values. The child likelihoods already contain their nature probability, so multiplying by it again is wrong. The minimum at each shared history is one common policy's optimum for this scalar objective; randomized choices cannot improve a scalar finite-history minimum. Then

`max(0,F(lambda,mu)-sum_h mu_h B_h)`

is a valid exact lower bound on the constrained minimax risk. This follows immediately from weighted risk <= maximum risk and `cost_h<=B_h`. Rational LP multipliers may propose good `lambda,mu`, but exact Bellman evaluation supplies the certificate independently of their numerical optimality. A rational feasible recovered policy supplies the upper bound. This construction matches `frontier.py` and avoids claiming floating LP residuals are formal dual feasibility.

## 6. Exact counterexamples and a closed-form frontier

### 6.1 Separate environment policies are clairvoyant

With no informative query, two catalog members require opposite answers. Any shared policy has errors `(p,1-p)` and minimax error at least `1/2`. Allowing a separate terminal policy for each member spuriously gives zero. Shared realization weights retain the `1/2` obstruction.

### 6.2 KL feasibility does not imply attainable error

One legal query fits the deadline; it costs one unit and gives three outcomes. Its laws are

`P0=(89/100, 1/10, 1/100)`, `P1=(1/100, 1/10, 89/100)`.

The middle outcome is ambiguous. Query once; answer 0 on the first, 1 on the third, and flip a fair coin on the middle. Each error is exactly `3/50=.06`. For every decision rule the sum of errors is at least `sum_o min(P0(o),P1(o))=3/25`, so this is the exact minimax optimum. At target `.05`, both KL constraints are nevertheless satisfied by one query:

`KL(P0||P1)=KL(P1||P0)=.88 log(89) > .9 log(19)=kl(.95,.05)`.

Thus the older necessary KL/flow program can be feasible while the exact shared-policy problem is infeasible. This is not a numerical solver artifact.

If `B` is the maximum expected query charge under each model, the exact frontier is

`R*(B)=1/2-(11/25)B` for `0<=B<=1`, and `R*(B)=3/50` for `B>=1`.

To attain it, query with probability `min(B,1)` and otherwise output a fair random answer. The lower bound follows because, conditional on no query, the sum of errors is one; conditional on querying it is at least `3/25`. Therefore `.5(error0+error1)+.44*cost>=.5`, and also `max(error0,error1)>=.06`. These are explicit supporting certificates. For `.06<=delta<=.5`, minimum expected charge is `(1/2-delta)/(11/25)`. Below `.06` it is impossible regardless of the available expected-charge budget.

This example also requires randomization: among deterministic one-query terminal rules, the smallest maximum error is `.11` because the ambiguous middle response must be assigned to one member. Deterministic-only enumeration would report the wrong randomized frontier.

### 6.3 Censoring destroys unavailable label/duration information

Let the two raw rows on `(label,duration)=(0,1),(1,1),(0,2),(1,2)` be

`P0=(.4,.1,.1,.4)`, `P1=(.1,.4,.4,.1)`.

Both label and duration marginals are identical across models. Full joint observation has minimax error `.2`. With cap 1 the observable rows become `(.4,.1,.5)` and `(.1,.4,.5)` on `(label0 at1,label1 at1,timeout)`; minimax error is `.35`. The timeout reveals neither the future label nor duration-2 joint parity. Query count is one in both cases; expected consumed time is respectively `1` and `1.5`. Under hard deadline 1, the cap-2 query is illegal. A fictitious leaked future label would invalidate the claim.

## 7. Finite-sample bridge to estimated rows

The finite-model theorem treats catalog laws as supplied. Suppose instead a separate paid, legal calibration interface produces a simultaneous event on which every cap-specific conditional row differs from its estimate by at most `epsilon` in total variation. Assume a common legal history tree, at most `L` queries, and resource totals in `[0,Cmax]`. The old learned-stateful coupling argument then gives, uniformly over every fixed history policy, including a policy selected from the calibrated table,

`|risk_h(true)-risk_h(fitted)| <= Gamma_L=1-(1-epsilon)^L`,

`|cost_h(true)-cost_h(fitted)| <= Cmax*Gamma_L`.

Proof: couple the two processes identically until the first differing query event; each conditional matched-history query couples with probability at least `1-epsilon`. Thus the entire transcript differs with probability at most `Gamma_L`; bounded loss and bill differences give the formulas. STOP and legal fallback at model-zero histories are necessary. No posterior-stability assertion is needed.

Consequently solving the fitted sequence-form LP with targets `delta-Gamma_L` and `B-Cmax*Gamma_L` gives a confidence-qualified feasible policy **if** those tightened constraints are feasible. A prior STOP fallback may be economically safe but is not generally uniformly `delta`-correct for an identification target below `.5`. Empty tightened feasibility must remain empty; it cannot be relabeled closed by using STOP.

This uses the same classical simulation argument already proved in `ndu_learned_stateful/THEORY.md`; the new LP does not remove its sample cost or make a vacuous confidence radius useful.

A structure-aware nonvacuous illustration exists in the symmetric three-outcome example. In a paid labeled calibration trial record `W=1` for the wrong extreme response, `W=1/2` for ambiguity, and `W=0` for the correct extreme. Its mean is exactly the balanced-query error `e`. For fixed `n`, Hoeffding gives `e<=e_hat+sqrt(log(1/alpha)/(2n))` with one-sided confidence `1-alpha`; use `log(2/alpha)` if requiring two sides. Provided the same symmetry and answer orientation are supplied to all methods, a query probability `r` has error `.5(1-r)+r e` and charge `r`. Hence a valid learned certificate is obtained whenever `e_upper<=delta` by choosing `r=(.5-delta)/(.5-e_upper)`. This avoids certifying unused kernel coordinates, but it is a classical decision-statistic estimator, not evidence of superiority over the same-structure baseline. The calibration and planning bill must be charged at the declared deployment volume. The numerical companion gives confidence arithmetic for a constructed count triple, not sampled data or a provider invoice.

## 8. Primary nearest neighbors and novelty boundary

1. Michael Fauss and Abdelhak M. Zoubir, **A Linear Programming Approach to Sequential Hypothesis Testing**, Sequential Analysis, 2015. The primary abstract explicitly formulates optimal binary sequential testing as an LP via its stopping-problem dual: https://arxiv.org/abs/1501.05870 . Thus an LP test formulation alone is not original.
2. Daphne Koller, Nimrod Megiddo, and Bernhard von Stengel, **Efficient Computation of Equilibria for Extensive Two-Person Games**, Games and Economic Behavior 14, 247–259, 1996. Perfect-recall sequence form is established: https://research.ibm.com/publications/efficient-computation-of-equilibria-for-extensive-two-person-games .
3. Raghav Aras, Alain Dutech, and François Charpillet, **Mixed Integer Linear Programming for Exact Finite-Horizon Planning in Decentralized POMDPs**, ICAPS 2007. Uses sequence-form policies for finite-horizon partially observed planning: https://cdn.aaai.org/ICAPS/2007/ICAPS07-003.pdf . The present single controller has linear rather than decentralized multilinear joint-policy scores.
4. Majid Khonji and Duoaa Khalifa, **Heuristic Search in Dual Space for Constrained Fixed-Horizon POMDPs with Durative Actions**, AAAI 2023: https://ojs.aaai.org/index.php/AAAI/article/view/26743 . Durative constrained POMDPs and dual planning are direct predecessors. The related journal article is https://doi.org/10.1016/j.artint.2023.103968 .
5. Sirin Nitinawarat and Venugopal V. Veeravalli, **Controlled Sensing for Sequential Multihypothesis Testing with Controlled Markovian Observations and Non-Uniform Control Cost**, Sequential Analysis 2015: https://arxiv.org/abs/1310.1844 . Controlled state and unequal observation costs are already explicit.
6. Chen Cheng and Xun Huan, **Optimal Stopping for Sequential Bayesian Experimental Design**, revision 3 dated 2026-06-13: https://arxiv.org/html/2509.21734v3 . Joint design/stopping and value-based stopping, including physical state, are already explicit.
7. Kellen Kanarios, Qining Zhang, and Lei Ying, **Cost Aware Best Arm Identification**, RLJ 2024: https://rlj.org/papers/kanarios2024cost ; Michael O. Harding and Kirthevasan Kandasamy, **Balancing Performance and Costs in Best Arm Identification**, NeurIPS 2025: https://papers.nips.cc/paper_files/paper/2025/hash/b0dfe8236981ba84b4d98a7ed0426f0b-Abstract-Conference.html . These rule out claiming novelty from cost-normalized identification or terminal penalty plus sampling cost alone.

The defensible current increment is an executable, internally reviewed, exact finite-model attainment reference with a concrete common-policy/censoring contract and explicit counterexamples. It can reject false deadline feasibility or expose a learned policy gap. New RL originality, external mathematical reconstruction, unrestricted unknown-kernel guarantees and independent actual-LLM net benefit remain separate open requirements.
