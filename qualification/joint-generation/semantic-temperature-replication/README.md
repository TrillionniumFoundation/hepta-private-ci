# Fixed independent-seed and new-noise calibration replication

This replication does not change the qualified FIT-only calibration algorithm,
[1/8,8] inverse-temperature interval, fixed28evaluations/head or originalfivequality
gates. It tests the earlier generic calibration signal rather than choosing another
reward/temperature sweep or claiming that calibration is NDU-specific learning.

New modelinitializations37/53 are prepared fromscratch with the original300decoder
and500supervised steps, followed by original-reward independentA/N300step adaptation.
The four models receive identical FIT-only twohead calibration work. Allmodels and
allcalibrators freeze before newvalidationnoise generation. Allnewbasepreparation
is charged inside this run; no pretrainedmodel bundle is restored.

`validation_noise.py` preserves the original validationgroup/order/renderer/noise
recipe while exposing only fixednew noise seeds9001/9002, sixvariants each. The
original86validationgroups are reused. These are new corruptions, **not new held-out
groups or TEST**. `test_noise_api.py` rejects otherseeds/variantcounts without
creating any validation examples. No originaldefault datasource is modified.

The explicit calibratedprofile preserves actual returnedCDF support/argmax or
refuses; marginalprobabilities andjoint quality may change. BothA andN are evaluated
with andwithout their own FITcalibrator,using ORIGINALreward. Eachnewnoise stratum
is reported separately,not selected. Generalcalibration andfairNDU incrementclaims
are separately gated,andthe overallgoal requires both. Poolednoise results remain
descriptive andcannot rescue a failed predeclared per-noise gate.

The fixed plan is `PLAN.md`. The previously qualified calibration implementation
andtests are in `../semantic-temperature/`; no algorithm/parameter bound was retuned.
The source-only API tests can be run from thisdirectory with:

```sh
PYTHONPATH=.. python -B -m unittest -v test_noise_api
```

Only portable source,APItests,plan andaggregates are public,not modelweights,private
runtime paths,rawpolicies orper-request modeloutputs. This finite RGB task doesnot
establish natural-image performance or restore the originaldigit-study payloads.

## Replication result: calibration passed, fair NDU threshold did not

The complete run passed all21literal tests andbothfreeze barriers. General FIT-only
calibration passed **8/8 predeclared modelseed xnoise xA/N contrasts** under the
originalfivegates. Greedytext stayedexactlyunchanged; probabilitymass,jointsuccess
andpixelMSE improved. All8fitted temperatures hadinterior roots; nobound changed.

OriginaljointCE changes onpartialcommands,macroaveragingfull/low:

| New model seed | New noise seed | A self-calibration | N self-calibration | Fair calibrated N−A | NDU five-gate pass |
|---:|---:|---:|---:|---:|---|
| 37 | 9001 | +0.031322 | +0.023193 | +0.003992 | No |
| 37 | 9002 | +0.027965 | +0.021196 | +0.005414 | Yes |
| 53 | 9001 | +0.033602 | +0.027227 | +0.004107 | No |
| 53 | 9002 | +0.030313 | +0.024219 | +0.003853 | No |

FaircalibratedN−A passes only**1/4**; the otherthree fail onlythe unchanged0.005CE
threshold,not the no-regression metrics. Thus calibrationreplication=true,
fairNDUgate=false,**overall=false**. UncalibratedN−A passes4/4 inthis replication,
but it cannotreplace thefaircalibrated comparison. Poolednoise NDU gains0.004703 /
0.003980 also cannotrescue theprespecifiedper-noise failures. All24contrasts are
retained inSUMMARY,includingcontrols andpooleddescriptive results.

This reproduces a general probability-calibration benefit across newinitializations
andnewcorruptions ofthe same validationgroups. It doesnot establish NDU-specific
increment at thepredeclared size, freshgroup-level generalization,or improvedgreedy
classification. The priorresults andallthresholds remain intact.

## Complete cost

Whole waitedchild: **5.735433CPU seconds**,5.775907wall,83600KiB RSS,under20CPU/
90wall/512MiB/4MiB,CPU0/single-thread/existing sharedlock. This includesallnewbase
preparation:600decoder and1000supervisedupdates,plus1200adaptationupdates. Shared
base preparation was0.245781 /0.226102CPU withinthatwholechild,not an extra charge.
No modelcheckpoint was saved orrestored andno externalmodel/data payload wasread.

Ledger:5620forwards/383264rows;604decodecalls/7248images;224FITNLL evaluations/
698880head-rowevaluations;20640evaluationoutputtables plus8256internalbase tables
forcalibratedservice;16512actualCDFargmax and16512supportchecks,allpassed. Twofixed
noise datasets were generatedonlyafter allmodels/calibrators froze;TESTcalls0.

Observed calibratedcoupling/CDF/guard CPU was1.55–1.71times the corresponding
uncalibrated path acrossfourmodels. These are measured serving-path costs,not
matched-microbenchmark orend-to-end latency ratios. Calibration isnot free; a later
implementation optimization mustpreserve the same law andinclude itssetupcost.
Unused coupled/repairgradient auxiliaries fromolderexperiments were not computed
here,as prospectivelydeclared; bothA/N arms omittedthem equally. This lowerwholeCPU
isnot claimed as a speedup over thelargerprevious experiment.

Priorqualification/experiments remain separatehistory. Source/review,olderresearch
andunknownsupervisortails areadditionalnotzero. NoTEST or newheldoutgroups wereused.
