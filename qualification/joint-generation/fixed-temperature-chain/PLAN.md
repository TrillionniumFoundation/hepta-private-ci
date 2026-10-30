# Fixed-support, fixed-temperature coupling loss: literal qualification only

SOURCE ONLY. New explicit mode fixed-temperature-support-coupling-smooth-v1 and
LOSS_SCHEMA rgb-fixed-temperature-support-coupling-loss-v1. No scientific model/data
run, numerical execution or locking by producer. Independent static review then
separate once-run admission required. Earlier coupled-training failures stay final.

## Exact conditional smooth graph
Strictly positive rawbinary64 p/q,normalized in genuine longdouble -> fixed semantic
transport -> positivepowers onexactreachable support -> maximalsemanticcoupling ->
wholejoint normalization -> originalrho0/1.5 CE. FixedTemperatureLossProfile wraps
actual TemperatureProfile used by helper; its metadata binds bothtau.hex values,
modeldigest,semanticinventories,precision,mode/schema andunchangeddomain constants.
Tau remainsin[.125,8],fixed FIT-derived constant here. New/old envelope/mode mixing
rejects; no checkpointpayload promise. Old normalized.py/calibration.py byte-exact,
old/default serving unchanged. This loss is NOT derivative through binary64rounding
or through refittedtau(theta). Existing calibration service values are reference
checks within prospective1e-12, notbitwise equality: that service also rounds an
intermediate basecoupledCDF before extracting marginals.

LegalCommand API derives maps from boundsemantics. Optional explicitfixed_maps is
mutually exclusive withcommands and validates shape/range; it supports independent
one-/bothconstant domainfixtures. These maps are fixed requestconstants, notlearned.
Mapped structuralzeros are legitimate, never filled. Rawzero probabilities still
reject, so everyactualpreimage destination a_f(i)>0. Oldrawstrictpositive domain is
not weakened by feeding sparsecalibratedmarginals to anoldraw-policy API.

## Gradient proof and no missing normalization
The coupling kernel preserves oldwholejoint normalization including its total
normalizer derivative. Let dA,dB be per-row negativeutility derivatives BEFORE
batchmean. Compute h=A*(dA−sum(A*dA)) for the calibratedmarginal logits. Since
A_j∝a_j^tau, v_j=tau*h_j/a_j only onreachable support, and rawlogitgradient is
p_i*(v_f(i)−sum_l p_l*v_f(l))/n. Implementation equivalently computes
chain_i=tau*(p_i/a_f(i))*h_f(i), then(chain_i−p_i*sum(chain))/n.
The conditionalratio p_i/a_f(i)<=1 avoids forming potentiallyoverflowing1/a or
0/0; noepsilon/floor. Existing outputfiniteguards reject unresolved arithmetic.
Both power normalization andrawsoftmax normalization are included; /n applied ONCE.
Imagechain uses correctlyunpermuted coupling derivative. Ordinaryrowmean aligned
anchor.2 is external, unchanged, andadded separately infull-lossFD fixtures.

Bothconstant maps give outputfixedindexpair andexactzero utilitygradient (same or
different destinations); singleconstant doesNOT shortcut. Positive exactties are
checked AFTER powers, excludingonlyprovenbothconstant compositions. Retain original
64float64eps active-residualfloor,sqrt(float64eps)relativebalance and1e-12 raw/CDF
marginalchecks, actualbinary64CDF support/argmaxchecks. No generalizedderivative,
rowmask,thresholdrelaxation,divisionfloor or fallback. Requiregenuine longdouble.

## Fixed 26tests (not executed byproducer)
Twelveoldnormalized andsevenoldtemperature tests unchanged; sevennew parameterized
tests. No needrepeatold4incentivefixtures: newtest explicitly preserves itswitness.
Newtests:
1. Actualcalibration.apply_batch CDF-CE parity attaus(1,1),(.5,2),(.125,8),(8,.125)
   forrho0/1.5, legitimatepartialcommands andpermutedsemantics;1e-12. Tau1
   normalized.value_and_grad value/gradient parity1e-12; zero-sumlogitgradients.
2. Bothheads8coordinates pertemperature/rho pair,utility ANDutility+.2ordinaryanchor
   centeredFD h1e-6,absoluteerror<1e-7,unchangedtransformedbranchsignatures.
   Includesconstantrow zero derivatives;128scalarFDchecks, no branchselection.
3. Bothconstant same/differentdestinations,oneconstant nonzerodiffheadgradient,
   duplicated-row batchmean factor1/2 toverify /n once (tolerance1e-12).
4. Positive transformedtie withrawuniform/tau.125vs8 refused; fixeddyadicresidual
   2^-20 accepted and2^-50 refused, originalfloor unchanged. Additionalraw.99/.98
   dominantclass tau8/8 case mustreject transformedpositive-tie/residualdomain, not
   merely nonfiniteinputs. No row/temperature/floor relaxation inlaterdiagnostics.
5. Modalityswap includingtaus/semantics/Rtranspose;rewardtranslation.01;
   commonlogitshift z+3.25/w−2.5 andinputimmutability (value/gradient1e-12).
6. Originaltwo-support negativeleadingtext incentive survives taus(1,1),(2,.5)
   underA/N; no falseclaimtemperaturecorrects rewardincentive.
7. Boundprofile roundtrip/distinctidentity,wrongmode/model/tau/precision,
   nonfinite/boundedreward/rawzero/invalidmaps/risk rejection.
Fixtures are fixedhandmade12class arrays, notdatasets. Reference expcosts are
representedbinary64 as inoldnormalizedloss, not exacttranscendentalclaims.

## No premature science
A qualifiedconditionalchain would not establish benefit. Normalizedcoupled science
already failed versus strong independentN; positivepower preserves theknown
negativeleadingtext incentive. Any later FITdiagnostic/scientificcontrol requires
newapproval/freeze,strongfairbaselines,originalgates andexplicit frozen-vs-refitted
calibration semantics. No implicitcontinuation or oldfailedcampaign rescue.

## One bounded qualification proposal
5CPU/30wall/512MiB/4MiB,CPU0/one numericalthread,existing syntheticsharedlock,
nonblockingrefusal/no replacement/no retry. Completewait4 success/failure/kill records
actualCPU/wall/RSS/exit. All26tests/imports/referencecalls/FD perturbations inside
childCPU; historicalsource/review/supervisortail additionalnonzero. Exactsource
allowlist,network/descendants denied;0modelpayloads/0trainingupdates/0datasetrows.
OnlynewRUN_ONCE boundedJSON/stdout/stderr; originals immutable. No numericexecution
before exactfreeze/independentreview/admission.
