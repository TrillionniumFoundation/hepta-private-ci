# Fixed-zero exponential score — literal qualification only

New explicit mode/schema/profile, fixed64 rows/rho0 or1.5. Original reward units
and zero remain fixed. No shift/scale/rho fitting. s(R)=(1-exp(-rhoR))/rho, using
-expm1(-rhoR)/rho; rho0 is R. This is an exponential-utility score surrogate, NOT
original log NDU, not an unbiased logarithmic-risk estimator and not a bug repair.

For row CE ci computed at this same rho, E_out s(Ri)=-expm1(-rho ci)/rho.
If di is derivative of NEGATIVE mean rowCE (already1/64), new negative mean score
logit derivative is exp(-rho ci)*di. Equivalently it is Zbatch times global-risk
gradient, Zbatch=mean exp(-rho ci). This is the complete analytic composition,
not an instruction to differentiate a detached reweighted loss or to omit a chain.
Ordinary rowmean aligned anchor.2 is added separately, never weighted by the scale.
No changes to original helpers, reward table, serving, numeric guards or decoder.
The API assumes upstream CE/gradients correspond to this same rho; it cannot infer
provenance from arrays. Mode/profile rejects old global/group identities.

Plainmean score gradients at fixed parameters/dataset have correct expectation
under the exact uniform-inclusion sampler:8 of130 content groups,4 of6 variants,
bothchannels. Without-replacement dependencies do not change equal marginals.
This does NOT imply unbiased Adam updates or wholetraining optimizer behavior.
Unregularized monotonic equivalence to fullpopulation entropic risk does not imply
equivalent regularized optima: anchor scale remains fixed. Translating rewards byb
multiplies utilitygradients byexp(-rho b), hence changes relative anchor strength.
Originalzero is fixed here, not tuned. This could explain a scale mechanism; it
is not proof of a benefit in this finite network or the original five metrics.
Independent training versus coupled/calibrated serving mismatch remains.

## Literal tests:17 total
Old13 group/global/integration tests and helpers byte-exact plus4 new tests.
Handcrafted64rows/8groups with legalpartialmaps and heterogeneous original rewards
within[-.35,1]; no model/dataset. Direct transformed-reward expectation and direct
bothhead logitderivatives agree with the chain; transformed scores may fall below
-.35, so NEVER pass them into the original boundedRGB reward wrapper. Eightbothhead
utilityFD andeight fullutility+.2ordinaryanchorFD atstep1e-6/tolerance3e-8. Zglobal
identity, rho0 exactA values/gradients, fixedconstantCE scales, translation relation,
identity/nonfinite/shape/overflow refusals and immutability. Algebraic tolerance
3e-15, not bitwise for different ordered nonzero-rho sums. Originalrewardbounds are
fixture checks; general finiteCE arithmetic rejects nonfinite outputs, no floor.

5CPU/30wall/512MiB/4MiB, CPU0 onenumericalthread, existing synthetic sharedlock
nonblocking; fullwait4, no retry. Sourceallowlist, no payload/network/descendants.
All imports/tests/hashes/output counted in whole child; review/prep/supervisortail
additional unknown/notzero. SOURCE ONLY producer: no imports/numerics/lock/push.
Independent review and separate parent admission required before qualification.

## Later science not included or authorized by this package
FixedA/globalN/score xfour sourcebases, static64schedule300steps, ordinaryanchor.2,
oldFITcalibration and originalfive gates. Allarms would compute oldgroupA/N+globalN
+score equally; require exactfourbases/eightA-globalN historical digests/oldmetrics.
Primaryscore-A andscore-globalN each8unpooled gates. No freshdata/tau/rho search,
no claim that relative recovery versus weaker globalN beatsA. No scienceworker here.

## Explicit v2 fixture completion before any execution
The unexecuted v1 freeze5004e2634ed4833a33fb007ba0b5e7658fa05dad657f4666ce134f0bfd0e6016 remains immutable. v2 adds literal128-row rejection and checks original-vs-translated reward anchor gradients/value are byte-identical, while utility gradients follow the analytic scale. ConstantCE scales are explicitly not1. No new tests or scientificparameter changes. Even without anchor, Adam history and epsilon mean utility scaling is not generally update-scaling equivalence. Any subsequent score gain is not proof original NDU beats A.
