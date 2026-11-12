# Joint spatial / deterministic-delay / reset research candidate

This candidate retains a nodal active law under the fixed birth/death generator
from #6107, and transports lower-hit flux through deterministic delay before
reset. Probability and every signed content channel obey the same linear law:

`a'(t) = T^T a(t) + r * f(t-d) + r * initial_phase_release(t)`,
where `f(t)=k_lower^T a(t)`. The delayed source is the actual CTMC hit density
from dense method-of-steps histories. New hit masses are never spread uniformly
over an observation interval. Uniform/point packets from #6108 specify only the
initial refractory law; atoms release as exact state jumps at their deadline.

Delay is deterministic in the mathematical model. SciPy BDF integration and
dense-history interpolation have numerical error, which is separately checked
by tighter controls and an independent serial phase-type matrix exponential.
All source discontinuities and their delay shifts split the integration.
The tested candidate is not an exact floating-point semigroup or an autograd
network, and old posterior coefficients are not nodal masses.

Upper exits remain a separate **permanently active, nonreturning** compartment.
Their probability and content are retained, and active reward continues there.
This truncates returning paths; it is not the original returning exponential
tail. `basis_values` separately integrates the candidate, the continuous
finite-domain model with this upper convention, and the half-line reference
over identical original uniform/tail/phase laws. Spatial/reset interpolation
and truncation errors are reported separately, without cancellation admission.

`perpetual()` is derived from this same delay/reset dynamics, using its discrete
lower-hit Laplace transform and exact `exp(-q*d)` delay. A finite-horizon test
actually executes the DDE and verifies accrued reward plus its remaining-age
continuation against that backward value. It therefore does not substitute an
unrelated analytic value readout for unrepaired state dynamics.

Eight tests cover independent serial-CTMC M/H/R/A, signed-mark transport,
time-control and irregular-query convergence, initial atoms, initial uniform
release versus converged matrix quadrature, finite dynamic continuation,
upper escape, same-law spatial refinement, and rejection controls. Exact source
hashes, original logs and separate reviewer receipts accompany the execution.

```sh
OPENBLAS_NUM_THREADS=1 python -B -m unittest qualification.hcsn_joint_dde.test_model -v
```

Runtime: Python 3.12, NumPy, SciPy. The source limits horizon to 8, content to
16 channels, source/query counts and delay-shifted knot construction. These are
not complete process/energy bounds. Reset stencils must be interior; crossing
a nodal knot is not differentiable in the current piecewise-linear mapping.
Initial mass at the lower node is rejected, rather than silently credited as an
event. Repeated calls recompute a trajectory; no durable episode API is supplied.

This first stage is **Draft / HOLD_NO_GO**. It does not yet qualify mapping old
posterior laws into rollout state, full training gradients, rare-tail relative
accuracy, learned task benefit, strong baselines, C2 replay or production
adoption. The separate next stage applies the unchanged 1% continuation gate
to every original retained law; success there remains distinct from state
migration and learned-network qualification. Original artifacts are unchanged.
