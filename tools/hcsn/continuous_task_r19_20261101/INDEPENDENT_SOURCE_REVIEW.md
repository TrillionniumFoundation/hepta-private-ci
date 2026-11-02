# Independent source review: jump-aware task tangents

The reviewer read the unchanged R18 `task.py`, `jump_solver.py` and old
`gradients.py`, then the new candidate. The separate `audit.py` owns its own
parameter perturbation and uses the unchanged R18 jump solver for all finite
differences. It never calls the candidate perturbation helper to form a
numerical reference. No formal confirmation result is asserted here.

Within a fixed active branch, each implicit waiting step is an invertible
tridiagonal M-matrix system with selected obstacle rows replaced by identity.
The tangent obeys the differentiated linear system. The sigma source uses the
current **left** value's reflected second difference; the final post-admission
right value would be incorrect in that source. Reward base, amplitude and
sigmoid-slope derivatives enter both terminal values and STOP obstacles.

At an admission date `k*rho`, the left RESET obstacle must use the saved left
successor at `(k-1)*rho`. The right RESET obstacle instead uses the right
successor there. The candidate carries both value and tangent dictionaries;
it differentiates the left obstacle solve first, then the final max with the
new right obstacle. Its first admission correctly has no left RESET option.

Reset interpolation includes the direct segment slope for `reset_x` as well as
the interpolated successor tangent. Both stochastic-row retention coordinates
add the diagonal-minus-off-diagonal successor value. Both reset fees contribute
minus one in the matching current mode; recovery cost contributes `-rho`.

The checked formulas are derivatives of the selected fixed-grid numerical
branch. A hard action tie or interpolation knot can have no unique classical
derivative. Reset interpolation knots are rejected. Action ties are not globally
rejected; the API returns a selected-branch tangent and exposes branch masks.
The audit reports branch changes under perturbation and includes every grid
value in its error gate, without filtering those cells away. Neither passing
finite differences nor unchanged finite perturbation masks proves global
differentiability, continuum convergence or full financial/neural gradients.

Moving recovery, horizon, mesh and domain coordinates remain unsupported. Their
derivatives require separate delay/admission and moving-domain analysis. The
source review found no algebraic defect in the implemented thirteen fixed-mesh
coefficient recurrences. Formal numerical checks remain separately recorded.
