# Work-matched direct-A versus factorized-source-A

SOURCE ONLY; separate independent review and once-run admission before execution.
Qualified factorv3 helper/model andsix tests remain byte-exact. This is a learned
content representation prior comparison, not newNDU or a risk-normalizer rescue.

## Representation, information and work matching
Both architectures keep202->32->two12rawlogits/learned192pixeldecoder andsource
commandmask. Canonicalsourceattributes3x2x2 already derive fromsourceclass labels,
but injecting their independence is an additional semanticstructure prior. Output
freedom reduces11to4perhead;7 correlation degrees are lost. Sameparameters is not
samefunctionclass. Equalinitial tensors do NOT imply equalinitialpredictions.
Actualdecoder semantics are not trusted fromlabelIDs: bothtext/image observed maps
must exactlyequal canonical0..11 for everydirect/factor base, else wholeabort with
no remap/relabel/selection. Record observedmaps and requirepaired decoder tensors
exactlyequal afterprep. No renderer/targets/extra labels at service time; unchanged
actualdecodedobserver/transport/coupling/oldFITcalibration still governs service.

New MatchedSourceModel wrapper invokes raw JointModel._forward exactly once per
forward orgradients, with inheritedmask. Everyforward computes BOTHraw andfactor
laws, selects byexplicitrepresentation; everygradient computes qualifiedfactor
pullbacks and BOTHraw/factor parametergradient dictionaries, selectsone. Same
auxiliary operations are charged to BOTHarms; no doublefactorization/extraforward.
The discarded other-representation gradient dictionary uses the SELECTED law upstream
gradient. It is computational auxiliary only, NOT an objective-gradient estimate for
the other representation; only one selected objective is trained.
Qualifiedmodel/helper untouched. Directdigest delegates oldSourceSceneModel;
factordigest delegates qualifiedFactorizedSourceModel, preserving eachidentity.
Wrapper identity/representation additionallyrecorded; clone cleanmoments/tensorcopy,
allcheckpoint operationsdisabled. Workmatchingaux is benchmarkwork, NOT natural
serving latency or a deployment requirement. Strictpositive factoraux can reject
botharms; nofallback dropsaux to rescue a control.

## Fixed models, labels and exact historical controls
8ownbases and8adaptedmodels:direct/factor xfold0/1 xseed103/107. Instantiate each
pair simultaneously, requireallinitialtensorsexact. Eachbase300decoder updates and
500sourceCE updates, sameown130FITgroups/old1701/1702 noise andsame seed+1000 batch
sequence; source labels extracted ONLY fromownFIT catalog. All8base prep charged.
For eachpair reuse one immutable oldseed+9000 schedule300batches,8distinctgroups x
4of6 variants xpairedfull/low=64rows. Everyadaptation arm computes oldall_terms
fourbranches andgroupA/groupN auxiliaries, selects originalA utility plusordinary
alignedanchor.2, unchangedAdam/lr.003/300updates. No newrisk arm orfreshdata/seed/
temperature/semanticaxes/hyperparameter search. Candidatecorrelationloss mayhurt.

Direct4bases/4A requireexactdigests versus completed exponential-score study's
strongA, pluscompleteolduncal/calmetrics, FITrecords/profilekeys, basefullmetrics
andFIT/heldout manifests. No oldweights restored; factor has no targetdigest.
All8models freeze before16head oldFITcalibration; all16heads freeze beforeknown
3701/3702/3711/3712 heldoutregeneration. KnownoriginalFITgroups/noise, notglobally
newblind evidence; ownfoldgroups disjoint, originalTESTclosed.

## Original scientific gates
PrimaryfactorA-directA all8unpooled originalfivegates conjunction: CEgain>=.005,
textmass/greedytext/jointsuccess>=-1e-10 andpixelMSEincrease<=1e-10. Evaluation is
oldmeanrow coupled/calibratedservice, all11metrics/full-low-macro/all-partial.
36contrasts including12primarywithpooleddescriptions and24selfcal(twoarms).
Selfcal16unpooled andpooled aredescriptive, cannot rescueprimaryfailures. All8base
fullmetrics retained; no changes tooldnegative studies or thresholds.

## Literal suite, counters and actual cost
46tests before scientificdata: oldgrouped37 +qualifiedfactor6 +newmatched3.
Matchedfixtures proveexactoutputs/parametergrads/oneAdamsteptensors versusoldSource
andqualifiedFactor underbothsupervisedCE andpartialA+.2anchor, initialization/mode/
clone/checkpoint, andidenticalrawforward/projection/pullback/auxdict counts byrepr.
Toyinitializations/optimizerupdates counted separately andincluded inchildcost.
Scientific8baseinitializations+8clones/0restores;2400decoder+4000supervised+
2400adaptupdates.15248rawforwardbatches/1035200rows andsame source-maskcopies;
10352000zeroed instructionelements.2416decodecalls/28992images.
2FITdata/4heldoutdata/0TEST.2400all_terms/614400fourbranchrows;
4800groupaggregations/307200rowvisits/38400groupCEs.
1200schedulebatches/9600groupchoices/38400variantchoices/76800rows reusedpair.
8FITserve/12480tables;16heads/24960headrows/448NLLcalls/698880NLLrowevals.
48evalserve/74880tables/10782720entries/149760CDFchecks;
24960internalcalibrationtables/49920argmax+49920supportchecks;
16baseprofile/8calprofile roundtrips. ExactLEDGER.jsonasserted atterminal.

PERrepresentation:7624rawforwards/517600rows;15248projections/1035200rows;
6400pullbacks/409600rows;rawANDfactor parametergradientdicts each3200,
204800parametergradientrows. Qualifiedpullback internallyprojects once; counts
include that, no omittedprojection work. Perbase/permodel preparation/adaptation/
FIT/evaluation snapshots plusglobalWORK retained. Bothrepr exactledger asserted.
Wholechild SHAconstruction/updatebytes/copies measured, allaux/hash/init/clone/
calibration/data/serve costs charged; perstage/perarmactualCPU andfullwait4 retained.
Equaloperations/updates do not guarantee identicalactualCPU. No deployment-speed
claim fromworkmatchedarms. Unknown prior/review/supervisortail costs notzero.

30CPU/90wall/512MiB/4MiB CPU0singlethread, existingnonblocking syntheticlock,
sourceallowlist/no payload/network/descendants, fullwait4/no retries. Anycanonical,
identity, historicalcontrol, numericaldomain orbudgetfailure isterminal.
