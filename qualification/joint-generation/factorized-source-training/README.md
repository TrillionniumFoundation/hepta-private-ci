# Work-matched factorized source representation: original gate not met

**FactorA−directA passes0/8 primary five-gate comparisons. Overall false.**

This representation-only additive-utility comparison introduces a known canonical
source-label3×2×2 independence prior. It adds no labels or parameters, but reduces
head output freedom11→4 and removes seven correlation degrees. Equalparameters
and matchedinitialtensors do NOT mean equalfunctionclasses or initialpredictions.
A factorized marginal is not a guarantee of actualdecoded semantic correctness.

DirectA/factorA each own four source-supervised, instruction-masked bases across
folds0/1 andseeds103/107. Both use300decoder/500sourceCE/300adapt updates and the
same oldstatic64row groups/variants/full-low schedule, originalA+.2ordinaryanchor,
oldFITcalibration and originalreward/fivegates. Actualobserved text/image decoder
maps were canonical0..11 for all8bases; paireddecoder tensors matched. All4direct
base/4A digests, completeoldmetrics/FITrecords/profilekeys/datasets reproduced exactly.
All8models then16heads froze before previously studiedheldoutnoise regeneration.
No TEST, newglobalgroup/noise claim, target/renderer atservice or outcome selection.

Botharms explicitly compute raw andfactor laws andbothparametergradientdicts each
call, selectonly theirown. Discardedother-gradientdict usesselectedlawupstreamg:
it is computationalauxiliary, NOT the otherrepresentation's objectivegradient.
Workmatches exactly byrepresentation, but this benchmarkaux is not natural
serving cost and cannot support a deploymentspeed comparison. Qualifiedfactor
model/helper untouched; explicitwrapper/representationidentity supplementsdigests.

## Fixed results
Originalcalibrated partial-command full/lowmacro differences; MSEnegative isbetter:

| Fold | Seed | Noise | FactorA−directA CE | Pixel MSE change | Five-gate pass |
|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | +0.001029880 | -0.000037683 | False |
| 0 | 103 | 3702 | +0.001541301 | -0.000047687 | False |
| 0 | 107 | 3701 | +0.004136774 | -0.000099875 | False |
| 0 | 107 | 3702 | -0.000092925 | +0.000010752 | False |
| 1 | 103 | 3711 | +0.001351386 | -0.000044728 | False |
| 1 | 103 | 3712 | +0.004043990 | -0.000092008 | False |
| 1 | 107 | 3711 | +0.004784054 | -0.000094051 | False |
| 1 | 107 | 3712 | +0.003810990 | -0.000080435 | False |

Seven CE changes arepositive, but the maximum+.004784054 remains below unchanged
+.005. All8 text-mass andgreedytext changes arepositive;7 jointsuccess andMSE
comparisons improve, whileone regresses. These patterns do not rescue any of the
originaleight gates. All36comparisons, all11metrics/full-low-macro/all-partial/noise
strata, basefullmetrics, pooleddescriptions andselfcalibration remain inSUMMARY.
No threshold relaxation, favorablepooling, seedselection or retry. Any subsequent
mechanism is explicitly post-result research, not a prespecified confirmation.
This is not evidence that NDU training beats additive training: botharms useA.

## Tests, work and actual costs
46literaltests passed before FIT generation, including24toyinitializations and
10toyoptimizerupdates, separately counted andinsideactualcost. Qualifiedfactor
11test prerequisite cost.258624CPU s includes10toyinitializations, not0models.
Current child completelywaited20.483473CPU s/20.573936572wall s,94044KiB RSS,
under30CPU/90wall/512MiB/4MiB,CPU0/singlethread/existingnonblockinglock/no retry.

Scientific8baseinitializations+8clones,2400decoder+4000supervised+2400adaptupdates;
15248rawforwardbatches/1035200rows,2416decodecalls/28992images. PERrepresentation:
7624rawforwards/517600rows,15248projections/1035200rows,6400pullbacks/409600rows,
rawANDfactor parametergradientdicts each3200/204800rows. Counts include projection
insidepullback, no hiddenextraforward. Completeperbase/permodel phaseWORK snapshots,
SHAcounts, masks, datasetgeneration/FITfit/NLL/serving counters, actualstage/arm/base
costs andwait4receipt remain inSUMMARY. Equaloperations are not identicalCPUspend.
Allnewprep/auxiliarywork counted; priorresearch, preparation/review/supervisortail
remain additional and unknownoldercosts are notzero.

## Portable package
Sixfiles only:matchedwrapper/test,frozenPLAN,README,SUMMARY,VALIDATION. Qualified
`factorized_source.py`/`test_factorized_source.py` live in sibling factorized-source
package; dependencies are originalsource_scene/model/utility pluspublished
aligned/transport/control modules. Place these portablemodules on Pythonpath.
Literaltests usehandinputs, not scientificdata. No unrestrictedrunner, weights,
privateinput/runtimepaths, merge or deployment. Source/test/PLAN byteexact.
SUMMARY retains complete scalaraggregates, modelrecords/digests/modes, bothbarriers
andcanonicalmaps. VALIDATION binds exactsource/result/receipt/independentreviews;
scientificfailure remainsfalse despite literalqualification and reproducibilityPASS.
