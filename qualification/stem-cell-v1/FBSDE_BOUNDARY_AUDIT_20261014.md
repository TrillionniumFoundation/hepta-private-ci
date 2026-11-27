# Finite-tree NDU/BSDE mathematical qualification (research only)

The initial endpoint of the user's Tree-Graph proposal is NOT proven by finding
a leaf with a convenient final value. This additive reference checks one
**frozen, nonanticipative, information-set policy** across an entire bounded
tree. It uses exact rational probabilities and terminal truth supplied by a
registered source, ex-ante chance expectation, explicit AND obligations, a
legal-action OR decision, and the scalar centered martingale covariance/Z rule.

\`fbsde_boundary_audit.solve(plan, policy, interfaces=...)\` rejects incomplete
backward interface coverage, wrong intermediate continuations, future leakage
along deterministic edges, duplicate/missing outcomes, probability drift,
cross-information-set action divergence, cycles and unregistered actions.
\`exact_control(plan)\` exhaustively enumerates **policy assignments to observed
information sets**, never oracle choices by hidden future outcomes.

This is a **linear finite-tree BSDE special case with terminal Boolean
obligations**, not a general fully coupled FBSDE, generic stochastic calculus
solver, Neural Differential Utility trainer, language decoder, independently
observed utility model, production optimizer, or permission to promote weights.
The AND operator is deliberately restricted to deterministic verified terminal
requirements; joint stochastic logical dependencies need a separately admitted
state model, not unproved independence assumptions. The exact comparator is
deliberately strong: a neural FBSDE must beat it on independently validated
quality/resource terms before any benefit claim.

Source/terminal inputs still require source-owner authentication and
independent verification. A digest protects recorded research bytes only; it
does not certify source truth or independent acceptance. The local tests are
fixtures and do not constitute a reader/model benchmark.

Run: \`PYTHONPATH=qualification/stem-cell-v1 python -m unittest -v
qualification/stem-cell-v1/test_fbsde_boundary_audit.py\`.

Research extension of #1760, building on the numerical and nonanticipation
semantics of #1550 and finite-tree controls of #1546. Existing System2
callbacks, DecisionCell artifacts, utility.ndu owners, model selection and
FinalUse remain unchanged.


## Separate analytic globally admitted coupled-field reference

\`fbsde_regular_field.examine\` adds the deterministic but **fully
forward/backward coupled** scalar reference \`dX=Ydt\`, \`dY=-cXdt\`,
\`X(0)=x0\`, \`Y(T)=gX(T)\`. Before changing the short-horizon mesh it checks
the full horizon against the first regular decoupling-field pole and bounds
the field slope and denominators. The exact harmonic flow and backward
terminal-field transport verify each intermediate \`X,Y\` interface and
the whole-interval terminal condition, not merely the last local boundary.

The **wrong-reset** control independently reapplies the original terminal
slope at every segment: each local terminal condition is satisfied, yet
the stitched backward field jumps at intermediate interfaces. Near/beyond
the first pole we reject the *regular-global-field profile* even when
every short segment would look individually well-posed. This conservatively
does not claim every nonregular boundary formulation is insoluble.

This is a mathematically separate negative reference aligned with #1550's
analytic study; it is NOT a replacement for its noisy Brownian reference or
a certification of an arbitrary neural fully coupled stochastic FBSDE.

Run: \`PYTHONPATH=qualification/stem-cell-v1 python -m unittest -v
qualification/stem-cell-v1/test_fbsde_regular_field.py\`.
