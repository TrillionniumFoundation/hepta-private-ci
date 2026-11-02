# Independent pre-outcome source review

Reviewed `directional.py`, `task_directional.py`, `campaign.py`,
`PROTOCOL.json` and the independent `audit_ties.py` before formal evaluation.
No formal campaign outcome was inspected or generated for this review.

The directional primitive implements the correct critical complementarity
system: strict continuation rows enforce the differentiated equation, strict
contact rows enforce the obstacle derivative, and biactive rows retain both
inequalities and complementarity. Its source term is `drhs - dA*v`.
Every policy matrix keeps the M-matrix sign/strict-dominance structure.
The max primitive chooses the maximum of slopes at exact value ties rather
than arbitrarily selecting one value branch's derivative.

The task propagates distinct left and right delayed-reset successors. At an
admission date it solves the left obstacle first and then differentiates the
right admission maximum. The sigma source uses the current left value's
reflected curvature with the correct sign. Reset interpolation includes the
successor tangent and direct segment slope. The updated implementation uses
the actual spatial grid for one-sided segment selection at an exact grid knot.
Nonnegative-coordinate, reward-boundary and stochastic-row tangent constraints
reject directions that would leave the declared task domain at a boundary.

The exact tie profile has equal constant rewards and zero amplitudes and costs.
For the balanced matrix explicitly selected in this new protocol, all primal
values are exactly `.5` in real arithmetic; the binary coefficients `.75/.25`
also preserve this construction without a decimal-row-sum ambiguity. The
mathematically supplied all-biactive masks are appropriate to this profile.
Generic near-zero floating slacks remain explicitly unqualified as exact ties.
Ordinary floating residual statistics are not interval certificates.

The prospective roster fixes two meshes, 24 affine and 24 joint directions and
two positive perturbation steps before confirmation. It retains all 96 cases
and 192 differences, including failures. The affine family tests an exact
positive-homogeneous finite task law. The joint family's squared-step remainder
bound is a finite numerical test, not a continuum or uniform remainder theorem.
The protocol explicitly discloses that propagation-parameter first derivatives
are silent at this constant base; it does not claim all thirteen coordinates
make nonzero dynamical contributions. The three-node analytic mixed control
separately exercises a nonzero `dA*v` term.

With the protocol's balanced `.75/.25` matrix, the first-admission directional
values for reward directions `[+.1,-.1]` and its reverse are `[+.1,-.05]` and
`[-.05,+.1]`; their sum is `.05` in both modes. This differs from the inherited
unbalanced `.9/.1,.25/.75` matrix discussed as a separate example in the math
review. The campaign's `.05` expected array is correct for its explicit new
configuration. It tests a real delayed task admission, not only scalar max.

The independent controls use exhaustive primal policy enumeration for at most
three nodes, independently specified exact answers and one-sided quotients.
Their callback supplies exact classifications only for those constructed
solutions. There is no candidate perturbation helper in that reference.
The compressed raw records retain the complete registered primal, directional,
doubled-directional and perturbed-value arrays. An explicit file-size guard
protects the transport bound; a transport failure remains a failure.

This review found no remaining algebraic defect in the declared exact-tie
directional contract. Numerical qualification remains the separately frozen
campaign's responsibility. R19's original and smaller-step whole-array gates
remain failed. Moving lag/admission dates, generic tie certification, continuum
gradients, full financial/neural gradients and production adoption stay open.
