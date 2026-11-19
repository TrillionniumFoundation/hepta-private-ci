# Fixed three-way color/spatial representation comparison

SOURCE ONLY pending independentreview andseparatelaunch. Single fixed3x4 partition,
not a split/axis/seed/temperature/rho/anchor/epoch search. Post-result hypothesis
motivated by source renderer mask(shape,position) thencolor assignment, not proof
of posterior independence. Alloldgates/failures preserved, no NDUclaim.

## Representation and shared work
DirectA/full3x2x2A/colorSpatial3x4A use same202->32->two12rawheads/192pixeldecoder,
source mask andFITsourceclass labels. Knownlabel factors are extra semanticprior,
notextra labels ordecodedsemantic assurance. Outputfreedom11/4/5 respectively;
CS preservesjointshape-position butdropscolor-spatialcorrelations. Sameparams and
initialtensors notsamefunctionclasses/predictions. Canonicaldecodedobserver maps
bothtext/image mustequal0..11 forALL12bases; tripledecoder tensorsexact afterprep.
Failurewholeabort, no remap/relabel/selection or silentlyrelaxedprior.

TripleMatchedSourceModel rawforward once/call; everyforward computes raw/full/CS
laws; everygradient computes bothqualifiedpullbacks andraw/full/CS parametergradient
dictionaries, selects one explicitrepresentation. Bothqualifiedhelpers untouched.
Discardedothergradients useSELECTED upstream gradient: computationalauxiliary,
NOT validotherobjectiveestimates. No simultaneousmultiobjective training claim.
Oldmodeldigest delegatesSource/full/CS respectively; wrapperidentity additionally
frozen. Cleanclone, checkpointdisabled. Workmatches across3arms, notnaturaldeployment
latency; twoextraaux computations explicitly charged even tostrongdirectcontrol.

## Fixed data, updates and historical controls
12ownbases+12clones:3representations xfold0/1 xseed103/107. Tripleinstances initialized
simultaneously same seed; requireinitialtensors identical. Eachbase300decoder and
500sourceCE updates withsameoldseed+1000 sampler; eachclone300adapt updates with
sameoldstatic grouped64 schedule(seed+9000):8groups x4of6variants xfull/low. Schedule
computedoncepertriple. Everyarm oldall_terms fourbranches andgroupA/groupNaux;
selectA+ordinaryalignedanchor.2, originalAdam/lr.003. No newriskarm/freshnoise.
Source labels onlyownFITgroups.2sharedFIT datasets/4knownheldoutdatasets/0TEST.

Direct ANDfull historical8bases/8adaptmodels requireexactdigests andcompleteold
FITrecords/profilekeys, uncali/calmetrics/allbasefullmetrics anddatasetmanifests
againstcompleted two-way factorstudy, withoutrestoring payloads. CS hasnotargetdigest.
All12weights then24oldFIT-calibratedheads freeze beforeknown3701/3702/3711/3712
heldoutregeneration. OldFIT1560rows/head,[.125,8],28NLL/head unchanged. Knownoriginal
FITcatalog andnoise, permodelgroupheldout, notnewglobalblind evidence.

## Original scientific gates and separate descriptive mechanism strata
PrimaryCSA-directA8 ANDCSA-fullA8 unpooled originalfivegate conjunction: meanrow
coupled/calibrated CE gain>=.005, textmass/greedytext/jointsuccess>=-1e-10,
pixelMSEincrease<=1e-10. FullA-directA isdescriptivecontrol;24selfcalunpooled and
pooled descriptions neverrescue.72contrasts retainall11metrics/channels/populations.
No thresholdchange, favorablepooling, modelselection or retries.

Predescriptivecolor_only meanscolor explicit, shape/position keep. other_partial
meansone/twoexplicitattrs excludingcolor_only. Requiredisjoint/nonempty andunion
exactpartial; recordrows foreachfold/noise/pooled. Same11metrics/full-low-macro
computed fromalreadyproducedlaw/outputs, storedSEPARATELY inmechanism_strata soold
results schema/values remainbyte-exact.0extramodel/serve calls; reductionloops,
row/attributevisits andCPU explicitlycharged. This is notanothergate/subgrouprescue.
Same-rawpolicy theorem saysCS/fulltransport equalifshapeORposition set; it doesNOT
predict trainedmodels differonlyoncolor-only because trainingchangesrawp. No causal
attribution ofoldfailures fromthisdescriptivesplit.

## Tests and exact prospective work
55tests before scientificdata: old46 BYTE EXACT +qualifiedCS6 BYTE EXACT +newtriple3.
Triplefixtures compareforward/fullparametergradient andoneAdamsteptensors under
supervised andAanchor against originaldirect/full/CS models; identity/clone/checkpoint
and3repr operationcounters exact. Literaltoyinit/updates counted separately inchild.

12baseinitializations/12clones/0restores;3600decoder+6000supervised+3600adaptupdates.
22872rawforwards/1552800rows, same sourcecopies/15528000maskedzeros;
3624decodecalls/43488images.3600allterms/921600fourbranchrows;
7200groupaggregatecalls/460800rowvisits/57600groups.
1200schedulebatches/9600groupchoices/38400variantchoices/76800schedulerows reused3.
12FITserve/18720tables/24heads/37440headrows/672NLL/1048320NLLrowevals.
72evalserve/112320tables/16174080entries/224640CDFchecks;
37440internalcalibrationtables/74880argmax+74880supportchecks;
24baseprofile+12calprofile roundtrips. LEDGER hardasserted.

PERrepresentation:7624rawforwards/517600rows; fullprojection15248calls/1035200rows
ANDCSprojection same; fullpullback6400calls/409600rows ANDCSsame; raw/full/CS
parametergradientdicts each3200,204800rowvisits. Qualifiedpullbackinternalprojection
included, noextraforward.3repr exactWORK ledger andperbase/model phase snapshots.
Descriptivestrata432reductionrecords; rowvisits144*sum(perfoldpartialrowspernoise),
unspecifiedattributevisits/actualCPU recorded. BaselineevalCPU explicitlyincluded.
AllSHAconstruct/updatebytes/copies, data/prep/FIT/serve andactualarm/base/stagecosts
retained, wholechildwait4 counts imports/tests/aux/reductions/hash/output. Equal
operations/steps notidenticalactualCPU. Priorunknown/review/supervisortail notzero.

## Prospectively expanded total budget
60CPU/180wall/512MiB/4MiB CPU0singlethread, originalnonblockinglock/fullwait4/no
retry. Largerwholebudget announced BEFOREexecution:thirdarm/extraaux and12ownbase
prep areNOT free norwithinoldtwo-armspend. Perarm300/500/300 fixed. Sourceaudit
allowlist/no payload/network/descendants. Anyhistorical/canonical/numeric/budget
failureterminal. Producer SOURCE/ASTonly, no imports/numerics/data/model/lock/push.
