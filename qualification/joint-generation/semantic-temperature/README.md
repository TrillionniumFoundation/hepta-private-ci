# FIT-only post-transport temperature calibration, with both sides treated equally

This new opt-in serving profile calibrates actual pre-existing CDF marginals after
semantic transport. Each head uses a positive inverse-temperature power on its
existing support, then maximal semantic coupling forms the joint distribution.
Mathematically positive powers preserve support/ranking/argmax. The implementation
also checks the **actual returned binary64 CDF marginals** against the concrete old
CDF and rejects support/argmax changes rather than falling back. Marginal probability
mass, image MSE andjoint quality are not structurally preserved.

Only FIT fitting uses labels. Serving uses model-bound temperatures, raw policies
andcommands, no targetlabels or new renderer. The explicit new schema/mode/key binds
two hexadecimal parameters andnested model/numeric/semantic identities; old/new
loads reject mixing. Defaults and all prior scientific results remain unchanged.

The fitter minimizes each head's mean marginalNLL, convex in inverse temperature,
on the fixed prospective engineering interval[1/8,8]. Everyhead receives exactly
28objective evaluations:identity,bothbounds,24bisection midpoints andchosenpoint,
even forflat/boundaryoptima. Uniform-supportflat input selects identity. The interval
is not a validation search. FITNLL nonregression is checked; it isnot a generation
quality gate. Calibration modifies probabilities,not modelweights orclassrankings.

## Payload-free qualification

Seven tests passed in **0.179331CPU seconds**,0.183359wall,28972KiB RSS. NLL gradient/
Hessian finite-difference error1.53e-11; knownbinaryroot error1.59e-7 (<3e-7);
108command/temperature service cases preserved support/argmax, andunit-temperature
joint-table error2.78e-17. Boundary/flat fixedwork, identity binding, unsupported
labels, invalidtemperatures, immutability andnumericalsupport-loss refusal covered.
No model,data,FIT,VALorTEST payload was read inqualification. Limits5CPU30wall,
512MiB/4MiB,CPU0/single-thread/existing synthetic lock andcompletewait4.

Run portable literal tests from this directory using existing qualified dependencies:

```sh
PYTHONPATH=../coupled-simplex-longdouble:../coupled-law-gradient:../explicit-semantic-transport:../semantic-coupling:../transport-aligned-training:.. python -B -m unittest -v test_calibration
```

`PLAN.md` fixesqualification and`RUN_PLAN.md` fixes the equally treated stronger
baseline/candidate scientific comparison,originalreward andoriginal fivegates.
Allmodel/calibrator identities freeze before validation; no validation tuning or
fresh-heldout/natural-image claim. Only portable source,tests,plans andaggregates
arepublic,not private paths,weights orper-request modeloutputs.

## Paired scientific result: useful calibration, overall primary still failed

All eight prior model digests anduncalibrated results exactly reproduced. Strong
originalindependent A/N andcandidate repairedcoupled A/N each received the same
FIT-only twohead procedure. All16fittedheads/448NLL evaluations andall8calibrator
identities were fixedbefore anyvalidation. Fourteen heads hadinterior roots; the
two seed23candidateA heads reached the predeclaredupperbound8,which wasnot expanded.

**All four model families in both seeds passed the originalfivegates for calibration
relative to their own uncalibratedservice.** OriginaljointCE gains ranged+0.024543
to+0.050237; greedytext wasexactlyunchanged. This is a positive probability-calibration
result on this reusedsyntheticvalidation, not newfeature learning orNDU-specificgain.
The strongerbaseline also improved, so candidate-only calibration wouldmislead.

Partial-command full/low macro contrasts,seed11 / seed23:

| Contrast | Original joint CE change | Text mass change | Greedy text change | Joint success change | Pixel MSE change |
|---|---:|---:|---:|---:|---:|
| calibrated candidate N minus own uncalibrated N | +0.032715 / +0.041131 | +0.020766 / +0.023345 | 0 / 0 | +0.020859 / +0.024459 | −0.000533 / −0.000640 |
| calibrated stronger N minus own uncalibrated N | +0.024543 / +0.032278 | +0.015553 / +0.017983 | 0 / 0 | +0.015615 / +0.019396 | −0.000389 / −0.000468 |
| calibrated candidate N minus calibrated stronger N | +0.000935 / −0.000222 | +0.001327 / −0.002220 | +0.001603 / 0 | +0.000466 / −0.001512 | −0.000006 / +0.000022 |
| calibrated candidate N minus calibrated candidate A | +0.004296 / +0.003522 | +0.004070 / +0.004706 | +0.008013 / +0.003205 | +0.004559 / +0.005735 | −0.000097 / −0.000097 |

The **overall primary remainsfalse**. Fairly calibrated candidateN doesnotbeat the
fairly calibrated strongerN with the required0.005CE gain inbothseeds; its internal
N−A increment isalso below0.005. No threshold orrootinterval changed. Positive
selfcalibration isnot relabeled asNDU-specific improvement oroverall task success.
All18predeclared contrasts,not onlythepositive ones,remain inSUMMARY.

Whole science child: **19.082489CPU seconds**,19.174965wall,85820KiB RSS,under
40CPU/120wall/512MiB/4MiB,CPU0/single-thread/sharedsyntheticlock,completewait4.
The higherceiling prospectivelyincludedcalibration andpairedserving.2400reconstruction
updates,7236forwards/496080rows,9600commoncoupledgradientcalls/614400rows. Calibration:
16heads/49920headrows,448NLL evaluations/1397760head-row evaluations,24960FITbase
jointtables. Evaluation:18576outputjointtables plus8256internalbase tables innew
serving;16512actualCDF argmax and16512support rowchecks,allpassed. Per-model FIT
calibration cost0.207362–0.242552CPU; commonplannedwork isnot equalactualspend.

The new0.179331qualification,prior0.374525mechanism,0.782639numericqualification,
17.463560rewardrepair and11.247789originalcoupledcomparison,0.714013diagnosis,
2.117035oldnumericalabort,0.568155oldqualification and0.447929sum ofbasepreparation
prefixes remain separatehistory. Source/review,olderresearch andunknownsupervisor
tails areadditionalnotzero. Twoexistingbasebundles were restored; nonewmodel
checkpoint saved. NoTEST used. Reusedvalidation isexploratory,not freshheldout or
originaldigit/natural-image evidence. A fixed independentreplication,not a new
parameter sweep,is the appropriate next check ofthis calibration signal.
