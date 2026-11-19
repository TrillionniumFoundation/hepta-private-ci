# Fixed FIT-only post-transport temperature qualification

The prior repaired-coupledN retained greedy-text accuracy versus stronger originalN
in the four savedseed/channel aggregates but hadlower probabilitymass/CE. This is
motivation for a confidence-calibration control,not a proved miscalibration cause.
No further reward coefficients are adjusted. Strongbaseline andcandidate mustboth
receive the same FIT calibration before any new comparative validation.

## New explicit graph, not preserved full marginal law

Take actualprior normalized-coupling CDF marginals after semantictransport. For each
head independently use p_i(tau)=p_i^tau/sum_jp_j^tau over the existing positive
support,exactzeros unchanged. Positiveinverse temperature preserves exactsupport,
ranking andargmax. Reconstruct maximalsemantic coupling ofthese calibratedmarginals.
Servingchecks actualreturned binary64CDF support andargmax against the concrete
priorCDF andrejects numericalchange/no fallback. Marginal probabilities/joint
quality areNOT invariant. Raw/CDFmarginalchecks1e-12; no image renderer ortargets in
serving. Basecoupling iscomputed once,then newcoupling once; costs not hidden.

Distinct explicitmode/schema/key binds two exacthex temperatures andthe nested
model/numeric/semanticprofile. Old/new loads reject mixing andexpectedmode/model
mismatch. This profile isnot oldcheckpoint compatibility ordefault service change.

## Fixed FIT estimator, no validation tuning

Each head minimizes mean marginalNLL over ALL FIT rows in BOTH full/low channels,
including constantcommandrows. Fixed engineering intervaltau in[1/8,8],not chosen
fromvalidation. NLL isconvex inpositiveinverse temperature; derivative isexpected
logp−targetlogp,hessian variance(logp). Compute baseline,bothendpoints,24bisection
midpoints andchosenpoint:exact28evaluations perhead evenforboundary/flatoptimum.
Select boundary byderivative sign,interior bybracket midpoint,uniform-supportflat
case identity. Require FITNLL notworse thanidentity within1e-10. No modelupdate,
label-conditioned serving orvalidation-based root/bracket/model selection.

Seven literaltests:analyticNLLderivative/hessian vsFD(h1e-5,atol1e-8);knownbinary
interiorroot(error<3e-7);boundaries/flat exact28work;all36commands×3temperaturepairs
actualCDFsupport/argmax andidentitytableparity1e-12;distinctprofile/mode/model
roundtrip;invalidinputs/unsupportedtargets/immutability;explicit numericalsupport-
loss refusal. No model/dataset/FIT/VAL/TEST access inqualification itself.

One completelywaited payloadfree child underexisting syntheticsharedlock,
CPU0/singlethread,5CPU30wall512MiB4MiB,no descendants/network/retry. Freeze+STATIC
review beforeexecution. Allarithmetic/testcost counted; priorresearch/source/review
additionalnotfree. Any scientific phase needs a separatepredeclared same-treatment
baseline/candidate plan,allmodels/calibrators frozenbeforevalidation,originalreward
andunchangedfivegates. Qualification cannotestablish generationbenefit.
