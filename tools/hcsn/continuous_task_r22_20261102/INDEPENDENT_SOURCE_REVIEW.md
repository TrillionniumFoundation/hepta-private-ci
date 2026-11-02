# Independent post-freeze, pre-confirmation source review

The reviewer first verified every size and SHA256 in `SOURCE_FREEZE.json`:
all 17 frozen files matched. This review is additional read-only evidence and
is not part of that freeze. No fresh profile was drawn, no formal solver was
executed, and no frozen source or protocol was changed for this review.

Reviewed `solver.py`, `certificate.py`, `correction.py`,
`complex_reference.py`, `DERIVATIVE_CONTRACT.md` and `PROTOCOL.json`, with
limited inspection of dependency loading and the complex-reference call site.

## Mathematical and implementation checks

The residual comparison argument applies to the stated fixed-grid equations.
The reflected matrix has symbolically exact row sum one for its exact-real
binary inputs; its contact-row replacements do too. Componentwise minimum of
the STOP, available RESET and WAIT residuals therefore has the required
translation comparison bound. Outward intervals recompute those residuals
instead of accepting the candidate's residual summaries. Previous-time state
and tangent intervals feed the correct delayed left/right successors, so
uncertainty is propagated rather than silently reset between stages.

Strict branch tests use positive interval lower endpoints of unused slacks.
They do not classify proximity as equality. Once a contact is proved, narrowing
its state/tangent enclosure to the corresponding exact obstacle enclosure is
valid. The differentiated selected-policy systems retain identity/M-matrix
rows and the same comparison constant. Unknown ties remain unqualified.

The expression-identity scheme is appropriately scoped to one certificate
call. Reward identities distinguish mode and node. Reset identities include
mode, interpolation cell and every participating successor identity. Implicit
system identities include mode, the complete prior RHS identity vector,
selected policy and all contact identities. Matrix, costs, direction and
interpolation convention are fixed globally within the call. Thus two such
keys being identical denotes the same local analytic expression, rather than
merely similar numerical values. Unresolved expressions receive distinct
time/node identities. Structural equality is also checked for contradiction
with the interval enclosures.

For affine directions, all five nonlinear coordinates are held fixed. The
listed unused-slack lower bounds and most negative enclosed slack slopes give
conservative open validity radii. The implementation includes cost, fee,
reward nonnegativity and reward upper-domain limits and rounds the exported
radius down. Known nonidentical true max ties do not receive affine-radius
qualification. This is a local admission condition, not a repair of either
old finite-step gate.

The binary-rational nonconstant witness is correct. At zero its rewards are
`(5/8,3/8)` and mode-one reset continuation is `3/8`. The registered WAIT cost
strictly exceeds the discrete Lipschitz generator bound on both meshes, so the
pre-admission STOP construction is valid. The exact fee center gives directional
values zero and one for the opposed fee directions. Adjacent binary fee values
have genuinely nonzero exact-real gaps; interval separation can distinguish
them even if FP64 max operands round together. The explicit witness is confined
to its checked configuration, geometry, horizon and single fee direction.

The correction pass supplies a proved policy only after branch certification,
then rechecks the entire corrected derivative. It does not change the primal
equations or widen the tolerance. The complex reference independently replays
primal selected equations without importing tangent implementations. Its fixed
imaginary increment is an independent numerical derivative check on that
certified analytic branch; it is not an interval proof by itself.

## Admission wording and limits

One gate boundary should remain explicit: `qualified` tests the derivative
enclosure bound, branch certification and policy agreement. The primal enclosure
bound is computed and reported, but is not itself compared to the local
tolerance inside `qualified`. Therefore a statement that both primal and
derivative upper bounds passed the same threshold requires checking the
reported primal bounds separately. This does not invalidate the local
derivative certificate's stated mathematical argument.

No actual algebraic flaw was identified in the reviewed residual propagation,
strict policy proof, identity construction, affine-radius logic or explicit
binary witness. This is a source review, not fresh empirical confirmation or a
machine-checked proof. It trusts the frozen bundled mpmath outward-interval
implementation and ordinary Python/NumPy/SciPy execution; those dependencies
have not been formally verified here. Arbitrary unrecognized ties, moving
delay/domain, continuum/full-neural gradients and the old finite-step gates
remain outside the qualified scope.
