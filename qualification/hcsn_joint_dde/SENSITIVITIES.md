# Fixed-prior physical variational flow

This is a first-order Jacobian of the frozen **uniform-grid** JointModel.
It evolves primal and sensitivity states through the same deterministic-delay
method of steps. It does not change the original projected HCSN operator.

The parameter order is log boundary B, log drift mu, sigma, absolute reset Vr,
and discount q. The initial relative-coordinate probability, signed content
and phase laws are held fixed. Boundary and absolute reset enter through
xr=log(Vr)-B, with dxr/dB=-1 and dxr/dVr=1/Vr. The other boundary dependence of
a physical episode prior is absent from this API. These two reset-chain
columns are dependent and do not establish independent identification.

The variational equation includes generator and hit/upper-flux derivatives,
delayed-hit sensitivity, the reset interpolation derivative, q dependence of
discounted H/A integrators, exp(-q*delay), and the weighted remaining-phase
state. Probability and all signed marks share the same physical equation.
Reset knots and zero jump-rate edges refuse two-sided derivatives. Nonfinite
physical chain derivatives and returned arrays are rejected. An unfamiliar
spatial/model subclass is refused; graded-grid qualification is separate.

Five local tests pass. Three initial laws (active point, phase atom, phase
uniform) cover all 39 retained final output coordinates against two central
FD steps for all five parameters: 585 variational coordinates. Maximum
absolute difference to fine FD is 1.1111926601081734e-7; maximum coarse/fine
FD difference is 3.3083702444258734e-7. The fixed gate is 2e-6 absolute plus
3e-4 relative; individual raw arrays and steps are retained. Separate checks
cover B/Vr chain equality, marked mass conservation, initial zero-time atoms,
q-weighted phase, finite-chain rejection and new-geometry refusal.

Absolute error can dominate near-zero derivatives. The independent original
array review finds maximum defined ordinary relative error 1.0 in zero-signal
q/probability coordinates, with FD noise around 1e-11, and undefined ratios
at exact zero references. This is not relative rare-tail qualification.

The first test attempt had a fixture-construction error (float Packet mass
where exact Fraction was required); its original RED log is retained. The
corrected original and reviewed-source runs are distinct. Arrays, untouched
logs, source identities and independent reviews live in
evidence/physical-sensitivities-20261112. Tests precede final formatting;
the source-format mapping records AST equality. Hosted exact-source checks
are a separate result, not inferred from these local receipts.

```bash
python -B -m unittest qualification.hcsn_joint_dde.test_sensitivities -v
```

This limited physical Jacobian does not qualify new graded geometry, short-gap
continuum event accuracy, arbitrary parameter boxes, full network/prior AD,
second derivatives, full training replay, task benefit, hardware cost, energy
or adoption. The uniform candidate has a separate short-gap first-hit bias;
passing its derivatives does not repair that forward approximation. HOLD.
