# R22 local control-direction contract

The object is the solution of the existing finite space/time delayed-obstacle
equations, with input binary64 numbers and the returned binary64 grid nodes
interpreted as exact real constants. This is a changed and explicit derivative
contract: it is not the derivative of rounded floating-point instructions, a
continuum free-boundary theorem, or the original R20 finite-step acceptance gate.
R20 sources, samples, tolerances and failures remain unchanged.

V1's saved initial-left arrays were missing from its reported error maxima.
The solver initialized them correctly, and all78 retrospective records remain
valid evidence for that executed builder. A corruption probe exposed the
verifier-input hole before any fresh profile was drawn. V1 sources/results are
preserved separately. V2 includes both initial-left maxima, adds two explicit
corruption controls, and requires BOTH primal and derivative bounds below the
unchanged tolerance. This strengthens admission; seed, roster and steps remain
unchanged. Three fixed old cases are engineering revalidation, not fresh cases.

## Strict policies and an independent certificate

For each time/mode, write the left obstacle problem as
`min(v-g, v-B, A v-rhs)=0`, omitting unavailable `B`. The reflected tridiagonal
`A` has positive diagonal, nonpositive off-diagonal and exact row sum one.
It is a nonsingular M-matrix. Replacing selected rows by identity has the same
properties. If every applicable minimum residual has magnitude at most `r`,
comparison with the constant perturbations `v±r` bounds the solution error in
infinity norm by `r`. This also holds for the linear selected-policy derivative
system. The causal delay is finite and positive, so interval bounds from earlier
times propagate without a within-stage reset fixed point.

`certificate.py` recomputes the real coefficients, payoffs, resets and residuals
with outward interval arithmetic. It does not reuse candidate residuals. Strict
positive unused slacks prove the active policy. STOP and RESET contact rows are
then narrowed to their exact obstacle intervals; all WAIT rows retain residual
enclosures. Differentiated WAIT rows use `A z=drhs-dA v`, contact rows use the
selected obstacle slope, and post-admission maxima select their proved branch.
The complete left/right arrays, including their initial values, are checked.
Known expression identities permit identical analytic functions to share a
branch. The expression keys include the entire prior RHS identity, policy and
contact identities; numerical proximity is never used as an identity witness.

If an outward interval straddles an unrecognized genuine tie, qualification
fails. There is no numerical tie tolerance to enlarge. A proved strict policy
that disagrees with rounded numeric metadata triggers a second directional
solve with that policy, followed by complete recertification. This fixes an
actual max-selection defect without changing the primal problem or tolerances.
The certificate trusts the bundled mpmath interval implementation and the
stated M-matrix argument; it is not a machine-checked proof of its dependencies.

`complex_reference.py` independently replays only primal equations with the
certified comparisons frozen. It imports no tangent/derivative implementation.
Each selected equation is analytic in the parameter near the base point, so the
imaginary part at the preregistered imaginary increment `1e-30` gives a separate
numerical local derivative check. This does not shrink a real finite-difference
step until an old failed test passes. Actual enclosures establish classification
and candidate accuracy; complex replay adds independent numerical evidence.

For the eight affine coordinates (costs, fees, reward bases/amplitudes), a fixed
complete policy makes the full delayed map affine. The minimum positive
unused-slack/decreasing-slope ratio, also intersected with the input domain,
therefore gives a conservative open interval of exact affine validity. The
interval routine rounds the reported radius down. This statement does not
apply to sigma, reset position, transition retentions or reward slope, nor to
unresolved or genuine non-identical max ties. It is local admission rather
than a guarantee for either original R20 finite step.

## Independent nonconstant true and one-ulp near ties

The registered binary-rational family uses base rewards `(1/4,1/8)`, amplitudes
`(3/4,1/2)`, logistic slope one, reset zero, transition rows `(3/4,1/4)` and
`(1/4,3/4)`, sigma one, WAIT cost two, zero recovery cost, horizon and recovery
`1/4`, domain `[-4,4]`, and fees `(1/8,1/16)`. Both registered meshes have a
node at zero. Reward Lipschitz constant is at most `3/16`; even a reflected
boundary row has `L_h g ≤ (3/16)/dx ≤ 3/4 < 2`. Hence all pre-admission and
terminal-left solutions equal the nonconstant reward, with strict WAIT slack.

At zero, `g=(5/8,3/8)`. Mode-one reset value is
`(1/4)(5/8)+(3/4)(3/8)-1/16=3/8`. A positive fee direction has directional
maximum `max(0,-1)=0`; a negative direction has `max(0,+1)=1`.
For fees one ulp above or below `1/16`, the exact rational gap chooses STOP
or RESET respectively, even when FP64 subtraction rounds both primal max
operands to `3/8`. R20 then gives a wrong local slope in two opposite signed
near-tie tests. Outward interval separation selects the correct real branch.
The exact center uses this independently checked algebraic witness, not a
general assertion that all tiny differences are ties. No other true ties gain
qualification from this witness. The standalone checker reconstructs the full
directional oracle from `Fraction(fee)` and grid geometry.

The earlier independent `MATH_ANALYSIS.md` gives another decimal-real example
and motivated this binary family. That decimal example is not the executable
registration. All formal inputs and the exact binary witness are in
`PROTOCOL.json` and the frozen executable source.

## Diagnosis and limits

For every old sample and both unchanged real steps, saved arrays decompose the
observed discrepancy exactly into frozen-policy truncation and policy-switch
components. Agreement of the local derivative with the independent reference
cannot retroactively pass R20's `1e-6` finite-step gate. The old worst fee case
has a first switching radius about `6.90e-6`, smaller than both `1e-4` and
`3e-5`; its local STOP slope is zero while the finite secants are nonzero.
The fresh six-profile roster checks all 13 signed coordinates without selecting
passing rows. Any unresolved branch or excessive complete-array error fails.

Arbitrary unrecognized ties, moving recovery/horizon/domain, continuum and full
neural gradients, the analytic-core D−B contribution, production/GPU/energy
ownership and the old generic finite-step gate remain open.
