# Fixed independent-initialization and new-validation-noise replication

The previous exploratory FIT-only calibration improved all8selfcomparisons, while
faircalibrated NDU-specific/strongbaseline gates stillfailed. This replication
freezes the existing calibrationalgorithm andqualitythresholds; it is not a sweep
of temperatures,learning rates,rewards,seeds orvalidation noise.

## New independent initializations, unchanged stronger baseline training

Modelseeds37 and53 fixed beforeanytraining. Generate originaltrain split once with
its unchanged seed101,260groups/1560rows,6variants. Prepare eachbase using exact
original32hiddenmodel,300decodersteps lr.05,500supervisedsteps/batch64/lr.003 and
seed+1000 mixedfull/low sampler. The preparationcost is NEW andincluded,nobase
payload restored. BothA/N clones sharethatonebase,optimizerreset exactlyasbefore.
Fouradaptedmodels:original-reward independentA/N x2seeds,300steps,batch64,lr.003,
anchor.2,rho1.5,seed+9000 sampler,originalAdam/normclip5,frozendecoder.
Compute allfour original/aligned utility branches andtwoanchors in everyarm and
retain the same extra readonlybaseforward. Unused coupled/repair gradients from
olderexperiments are not recomputed:they never affect these modelupdates andtheir
omission applies equallyto A/N. No reward repair ornewcoupled-trainedfamily here.

Allfourfinalmodels freeze beforecalibration. Everymodel's twoheads usesall3120
train full+low rows,FIT-only NLL andthe exactqualifiedinverse-temperature interval
[1/8,8],24bisectionsteps,28objectiveevaluations/head includingbound/flat cases.
No expansion ofthe boundseen inpreviousresults. Allfourcalibrators freeze BEFORE
anynewvalidation-noise generation. No modelcheckpoint saved orloaded.

## Fixednewnoise, not newheld-outgroups andnotTEST

Only afterbothbarriers,generate validationcorruptions with fixednoise seeds9001
and9002,each using the original86validationgroups/516rows/312partial andsameuniform
noise(.03,.25),normalcorruption,clipping andthumbnailrecipe. The newwrapper exposes
onlythese two validation-noise requests,neverTEST. Sourcebody/order isunchanged
apartfromnoise-seed parameter. Samegroup/target/command inventories acrossnoise
replicates;distinct inputhashes andtrain-group separation checked. This is independent
noise on alreadyusedheld-outgroups,NOT fresh group-level generalization evidence.

Sameactual normalizedcoupled service anditsFITcalibratedcounterpart evaluate all
fourmodels; reuseidentical rawforwards forpairedservice. Bases areuncalibrated
referenceonly. Originalreward,allmetrics andactualCDFsupport/argmaxchecks unchanged.
Storemetrics separatelyforEACHnoiseseed andtheirpooledmacro; no bestnoise selection.
Greedy invariance isstructural andnot a new learnedclassification improvement.

## Originalgates,calibration claim andNDU claim kept separate

For eachof2modelseeds x2noiseseeds:
- CalibratedA minusitsuncalibratedA andcalibratedN minusitsuncalibratedN:8calibration
  contrasts must eachpass allfiveoriginalgates for the calibrationreplication claim.
- CalibratedN minuscalibratedA:4contrasts musteachpass thesamefivegates for the NDU
  incrementclaim. UncalibratedN−A andpoolednoisecontrasts also reported,not selected.
Fivegates remain originaljointCEgain>=.005,textmass/greedytext/jointsuccess changes
>=−1e-10,andpixelMSEincrease<=1e-10. Overallgoal passesONLYif bothclaimfamilies pass.
NoNDUclaim isrescued bygeneralcalibration success; nojointMAP replacement orTEST.

## Resource/control ledger

One child,existingsyntheticlock,CPU0/singlethread,20CPU90wall512MiB4MiB,fullwait4,
no retries/extensions.21literaltests (12numeric+7calibration+2newwrapperrejectiontests) beforemodels.
No model/datasetpayload reads: allnewsyntheticpreparation isinsidewholechild.
Expected2baseinitializations,600decoderupdates,1000supervisedupdates,4clones,
1200adaptationupdates;5620forwardbatches/383264rows (2000pretrain,3600adaptation,
8FIT,12evaluationforwards);604decodecalls/7248images inclfinaldecoderloss andobserver;
4FITbasecouplingbatches/12480tables,8heads/24960headrows,224NLL evaluations/
698880head-rowevaluations;20evaluationcalls/20640outputtables/2972160entries,
41280CDFmarginalchecks plus8256internalbase tables in calibratedservice;
16512argmax and16512support rowchecks;6old/4newprofile roundtrips. No unusedcoupled
gradient workloadclaimed. Preparation/adaptation/FIT/evaluationcosts recorded and
included,not inheritedfree. Historicalresearch/qualifications areseparate; source/
review/supervisortailsadditional. Allfailures terminal withactualphase/counters.
