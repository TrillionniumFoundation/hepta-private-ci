# Independent diffusion microdomains with a smooth first-hit release

A unit starts each one-step transition with a common log safety distance \(x\). Its \(n\) subunits then undergo conditionally independent Brownian diffusion with drift \(\mu\), volatility \(\sigma>0\) and common absorbing wall zero for duration \(T>0\). The first hit by any subunit releases the packet. If release occurs the next margin is the reset level \(\rho\). If all survive it is their arithmetic mean endpoint. This gives both a differentiable release and a consistent conditional expected next state. A common moving drive may set the wall at the beginning of an interval. Correlated noise and a moving wall inside the interval require a different joint first-passage law.

## One-step closed form

Let \(F\) be the original one-path first-hit probability, \(S=1-F\), \(s=\sigma\sqrt{T}\), \(d=\mu T\), and \(H=e^{-2\mu x/\sigma^2}\Phi((d-x)/s)\). For \(x>0\), reflection at the wall gives

\[
F=\Phi((-x-d)/s)+H,\qquad m=E[X_T\mathbf{1}_{\tau>T}]=(x+d)S+2xH.
\]

The normal density terms in the two truncated first moments cancel. Since all other paths must survive for a single endpoint to contribute, independence and linearity give

\[
q_n=1-S^n,\qquad M_n=m S^{n-1}+\rho q_n .
\]

At \(x\le0\) set \(q_n=1\) and \(M_n=\rho\). At \(n=1\) this reproduces the original finite-horizon release and expected-reset update. Near the wall, \(S=ax+O(x^2)\) and \(m=O(x)\), so \(1-q_n\) and \(M_n-\rho\) both scale as \(O(x^n)\). Analyticity on the live side makes the stopped extension \(C^{n-1}\). With two paths the first derivatives match, and the original value channel already has a zero continuation-side slope. The flatter near-wall derivative can reduce sensitivity during training. The single-path equity remains a feature of each subunit. A valuation problem with joint default at the earliest hit would have its own continuation equation. Propagating only \(M_n\) in later time intervals is a mean-state closure and does not propagate the complete joint distribution.

The independent minimum-time survival identity is classical. Lawley, *Physical Review E* 101, 012413 (2020), treats fastest first passage of multiple diffusion searchers (https://doi.org/10.1103/PhysRevE.101.012413). NIST's series reliability model gives the same product structure (https://www.itl.nist.gov/div898/handbook/apr/section1/apr182.htm). The construction here couples the minimum-time event to a network's differentiable wall/reset transition, its local inverse, and the existing He–Xiong single-path equity feature. The deterministic novelty screen searched 7,394 distinct previously identified HCSN code/document/config blobs (56,680,068 bytes). The two direct survival-power patterns had no hits. The one textual `competing-risk` match concerned mutually exclusive first exits at opposite boundaries on one path. Many other textual matches concern independent verification of single-path equations. Search coverage and match text appear in `precedent_screen.json`. Alternate wording and code named outside this corpus limit any priority conclusion.

## Editing one local probability

At zero log drift, \(F=2\Phi(-x/s)\). For an interior target \(q^*\),

\[
F^*=1-(1-q^*)^{1/n},\quad x^*=-s\Phi^{-1}(F^*/2),\quad B^*=V e^{-x^*}.
\]

With the He–Xiong boundary \(B=\beta_C C+\beta_P P\) and bounded drive \(P=P_0(1+\eta\tanh a)\), solve \(P^*=(B^*-\beta_C C)/\beta_P\) and \(a^*=\operatorname{atanh}[(P^*/P_0-1)/\eta]\). Positive slope, positive state and an interior reachable boundary are necessary for a finite unique active-state solution. The absorbing target one permits several preactivations. The implementation preserves a preactivation that already achieves it and otherwise attempts the wall. Zero hit probability requires infinite live distance at positive horizon and volatility. For nonzero drift this implementation reports that the closed inverse does not apply.

With frozen keys \(K\) as rows and desired changes \(y\) to their preactivations, minimize \(\Delta w^\top C_w\Delta w\) subject to \(K\Delta w=y\), where \(C_w\) is positive definite. Cholesky whitening and the pseudoinverse provide the minimum-cost feasible update. A zero target change protects a stated key. Identical keys with incompatible targets make the system infeasible. All guarantees condition on fixed earlier states, keys and feedback. They do not propagate through arbitrary unseen or subsequently changed representations.

## Numerical evidence

With float64 and the original one-path calibration, n=1 agrees with the source to 1.11e−16 in probability and 5.55e−17 in next margin. For n in {1,2,3,4}, central finite-difference gradient errors on four interior points were below 3.60e−10 in probability and 1.74e−10 in next margin. At a distance of 1e−6, the two-path live-side release derivative was −1.15e−4 and the next-margin derivative was −1.75e−5. Both vanish at the absorbing extension. An independent exact conditional Brownian-bridge simulation covered two drifts, two start distances and n in {1,2,4}, with 140,000 joint paths per cell. Across those 12 cells, the largest absolute standardized discrepancy for release or mean margin was 2.36.

For a frozen input, the analytic write moved two-path risk from 0.7980661 to the requested 0.9764322 with zero reported double-precision probability error. A protected key's preactivation moved −1.56e−17. A separate unprotected key's risk moved from 0.5934245 to 0.5431942. Over 25 targets at each n in {1,2,4,8}, maximum inverse preactivation error was 5.33e−15. Examples verify unreachable boundaries, zero target, conflicting duplicate keys and a non-positive-definite cost matrix. This experiment demonstrates a local write with fixed representation and fixed diffusion parameters. It supplies no measured whole-model training-time ratio.

`microdomain.py` requires PyTorch. Run `python verify_microdomain.py verification.json` from this directory with the parent directory's registered `parent_cell.py` available. `PYTHONPATH=.. python law_lookup_audit.py` evaluates the old table's edge behavior. `FROZEN_DIAGNOSTIC.md` registers an independent CPU-only developmental comparison with previously trained scalar one-path captioners. The separate six-arm COCO experiment retains its original one-path specification.
