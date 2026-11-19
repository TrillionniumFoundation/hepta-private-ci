# Fixed FIT-only semantic-temperature comparison, no validation tuning

This is a new serving/calibration control, not another reward sweep or new feature
learner. The previously trained originalindependent andminimal-repaircoupled A/N
models are deterministically reconstructed andmust allmatch their alreadyfixed
digests. The calibration question is motivated by retainedgreedybutlowerprobability
mass in priorcandidate aggregates; that pattern alone doesnot prove miscalibration.
All earlier failures andoriginalreward remain immutable.

## Same modelwork andFITcalibration forstrongbaseline/candidate

Eight models:original-reward independentA/N andminimal-repair coupledA/N xseeds11/23.
Samebases,300updates,batch64,lr.003,anchor.2,rho1.5,originalAdam/normclip5 andsampler.
Asbefore allmodels compute originalfourutility branches/twoanchors andoriginal/
repaired coupledA/N on everybatch:9600newcoupled calls. Bothdecoders frozen.
All8originalfinaldigests must exactlymatch; this stage isnot choosing newmodels.
All8models freeze before calibrators,andallcalibrators freeze before validation.

ForEACHmodel fit two separateinverse temperatures using all1560FITrows inBOTH
full/lowchannels:3120rows/head,16heads total. Inputprobabilities are the concrete
priorCDFmarginals aftersemantictransport. Headtargets followfixedobservedsemantics.
Fullyspecifiedconstant rows retained. SamequalifiedNLL estimator,[1/8,8],24bisection
steps,exact28objectiveevaluations/head; noVAL/TEST data,root/bracket/hyperparameter
changes,seed/model selection orlabels inserving. Modelweights neverchange during
calibration. FitNLL improvement isnot a generation-quality gate.

## Pairedold/newservice,unchangedoriginalqualitygates

Afterthe allcalibratorbarrier,evaluate eachmodel under BOTHuncalibratednormalized
coupling anditsownFITcalibratedprofile on the samefixedvalidation. Everyactual
calibratedCDF checks support andgreedyargmax againstitsconcreteuncalibratedCDF;
no fallback. Originalmarginalprobabilities/pixelMSE/jointCE areNOT structurally
preserved. Originalreward used for allCE andoriginalfiveacceptance gates. The two
supervisedbases are uncalibratedreferenceonly,not primaryfitted baselines.

Primary partialcommandfull/lowmacro,inBOTHseeds:
1. calibrated repairedcoupledN minus calibrated originalindependentN;
2. calibrated repairedcoupledN minus calibrated repairedcoupledA;
3. calibrated repairedcoupledN minus itsuncalibratedself.
Allsixcontrasts must meet CEgain>=.005,textmass/greedytext/jointsuccess no regression
within1e-10,pixelMSEincrease<=1e-10. Retainpairwiseuncalibratedcontrolcontrasts,
calibratedindependentN−A,andcalibrationeffect oneachmodel. Positivepowers cannot
repair a pre-existing greedyregression; do notreinterpretgreedychanges aslearning.
JointMAP isnot substituted. Report allfull/low/all/partial andoriginalancillary
metrics. Reusedexploratoryvalidation only; noTEST,no freshgeneralization claim.

## Fixedresources andworkledger

One new child,existing syntheticlock,CPU0/singlethread,40CPU120wall512MiB4MiB,
fullwait4,no retries/extensions. The higherceiling explicitlyincludes fitting and
pairedserving,not equalhistoricalspend. Allmodels share the sameworkslots; actual
per-model/fitting/serving/wholechildcost measured. Existingtwo supervisedbasebundles
only; no newmodelcheckpoint saved. Bothpreviousqualified12+4tests andnew7tests
run beforemodels andcharged. Any numericrefusal terminates,norowdrop.

Expected2restores8clones2400updates;7236forwardbatches/496080rows (old7220/471120
plus16FITforwards/24960rows);2decoderobservations24images;2repairtablecalls3456entries;
9600coupledgradientcalls614400rows;8FITbasecouplingbatches24960tables;16fittedheads/
49920headrows,448NLLobjectiveevaluations/1397760head-row evaluations;all8calibrators
beforeVAL. Pairedserving adds16trainedmodelchannelcalls:36evaluationcalls18576tables,
2674944entries37152CDFmarginalchecks;10baseprofile and8newcalprofile roundtrips.
Eachcalibratedcall internallyconstructs bothbase andcalibratedtables,explicitly
charged. Counts describe top-level evaluationtables separately from thisinternal
basework. Fixedfirstrow scalarreference checks only20uncalibratedcalls. All32
trainedmodelservice/channel pairs compared forstrict marginalargmax (16paired
checks perhead) andsupport. Historicalresearch/calibrationqualification/baseprep
areseparatecosts,not zero; source/review/supervisortailsadditional.
