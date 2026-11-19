# Fixed raw versus Haar coordinates ONLY at adaptation boundary

SOURCE ONLY pendingindependentreview andonce-run admission. Onefixed2x2orthonormal
basis perRGBchannel, all192dimensions retained, no newsemanticlabels/factorprior/
riskweight/parametercount/functionclass. Samefunction atconversion up tofixed1e-12
engineering admissiontolerance; differentAdamcoordinate dynamics notguaranteedqualityimprovement.
Originalsource/Haarhelpers/testsuite unchanged. No nextbasis/scale/thresholdsearch.

## Shared raw pretraining and explicit work-matched conversion
Four exactraw SourceSceneModel bases, folds0/1,seeds103/107, oldownFIT130groups,
300decoder/500sourceCE each ONCE. Bothraw/Haar freshclones resetoptimizer andupdates
likeoldclones; Haarconversion ONLYatadaptationboundary. Sharedbasepreparation
chargedonce, notsilentlyretrainedperarm; inheritedcostnotfree. Source-classlabels,
commandmask, rawpretraining anddecoder remainunchanged.
Everyarm conversioncomputes encoder_coordinates once:rawdiscards,Haarselects.
Everyarm's maskedinput computesonehaar_features:rawdiscards,Haarselects. No transform
back duringupdates and no additionalnetworkforward. Originalsharedrawbase reference
forwards andpretraining are outsidearmtransformwrappers andchargedseparately.
This matchingaux isnotnaturaldeploymentcost; actualwork/CPU explicitlyreported.
Mode/profile/wrapperidentity separate, rawdigestdelegatesSource andHaardigest
qualifiedHaar; clone preservesalreadyconvertedweights, cleanmoments/checkpointreject.

Beforeanyadaptation for eachbase, inspectentirefixedFIT full ANDlow rows through
sharedbase andbothclones: hidden,textprob,imageprob differences<=1e-12, nonencoder
parameters includingdecoderexact.24additionalforwards/18720rows acrossfourbases,
not a free assertion. No tolerance widening orrow selection; failwhole onfirst
violation. Params noalias, originalbase frozen. Boundarymaxerrors/conversioncosts
andpartialfailedprefixpreparation/transformprogress retained.

Both8clones same300 oldgrouped64 schedule(seed+9000), A+ordinaryalignedanchor.2,
lr.003/originalAdam/normclip. Each64batch8groups×4of6variants×full/low; allarms old
all_terms fourbranches andgroupA/groupN auxiliaries, select originaladditive.
No newNDU, temperature/rho/anchor/noise/epochs/partition change. Botharms have same
initialfunctions, butcoordinatewiseAdammoments/squaring/epsilon makeupdatesnoncovariant.
SGD/activeglobalnormclip covariance isexact-arithmetic property, notbenefitclaim.

## Exact controls, barriers and original evaluation
Raw4bases/4adaptedmodels exacthistoricaldigests, fulloldbase/modeluncal-calmetrics,
FITrecords/profilekeys anddatasets requiredagainst completedfactorstudy'sdirectA.
Oldfullfactor fixedsavedmetrics retainedonlyasdescriptivereference: not retrained,
not gate/controlselection; its inherited20.483473CPUstudycost additional.
All8models freeze then16heads oldFIT-only calibration, all16heads freeze BEFORE
known3701/3702/3711/3712 heldoutnoise generation. Fixedold[.125,8]/28NLL/head.
OriginalTEST/VALclosed; reusedoriginalFITcatalog/knownnoise are notnewgloballyblind
validation. No seed/model/noise selection. Foursharedbasefullmetrics retained.

PrimaryHaarA−rawA all8unpooled originalfivegate conjunction: originalcoupled/calibrated
meanrowCEgain>=.005, textmass/greedytext/jointsuccess>=-1e-10,MSEincrease<=1e-10.
36contrasts retainall11metrics/full-low-macro/all-partial/noises;16selfcalunpooled
pluspooleddescriptions are notrescuegates. No gate thresholdchange orpoolrescue.

## Literal suite and complete work
47tests before scientificdata: oldgrouped37 byteexact +qualifiedHaar6 byteexact +
newmatched4. Newtests verify eachwrapper vsreference exactforward/parametergradient/
supervised andAanchor Adamstep tensors; A+.2anchor gradientcovariance and7actual
modelFDcoordinates; oneACTIVEnormclippedSGDcovariance; identity/clone/work/refusals.
QualifiedHaarconstructedAdamnoncovariance retained. Literaltoyinit/Adamupdates
counted;4manualSGDmodelsteps (2qualification+2activecliptest) separatelydisclosed.
Tests/FD/toywork notscientificupdates butfullyinchildactualCPU.

Scientific4baseinitializations/8freshconversions(8clones)/0restores,
1200decoder+2000supervised+2400adaptupdates. Baseline11240forwards/766720rows PLUS
boundary24forwards/18720rows =11264forwards/785440rows; sameSourcecopies/7854400zeros.
1208decodecalls/14496images.2FITdata/4knownheldout/0TEST.
2400all_terms/614400fourbranchrows;4800groupaggregations/307200rowvisits/38400groups.
1200schedulebatches/9600groupchoices/38400variantchoices/76800rows reused2arms.
8FITserve/12480tables/16heads/24960headrows/448NLL/698880NLLrowevals.
40evalserve/62400tables/8985600entries/124800CDFchecks;
24960internalcalibrationtables/49920argmax+49920supportchecks;
12baseprofile/8calprofile roundtrips. ExactLEDGER.jsonasserted.
PERarm:4encodertransformcalls/128rows (32encodercolumns each);
2424inputtransformcalls/178560rows includingboundary,FIT,eval.
Sharedbaseforwards excludedfromarmtransformcounts butincludedwholeforwardledger.
Work snapshots afterboundary/adaptation/FIT/eval, conversionCPU, sharedprep,
armadapt/eval/baseeval/FIT/data/serving costs, allSHAconstruct/updatebytes/copies and
wholewait4 retained. Failurekeeps completedprep/adapt andpartialboundarycosts/progress.
No hiddenfreeconversion orduplicateprepcharges; equalupdates notidenticalactualCPU.

30CPU/90wall/512MiB/4MiB CPU0singlethread, originallocknonblocking/fullwait4/no retry.
Sourceauditallowlist,no data/modelpayload/network/descendants. Allimports/tests/
conversion/transforms/metrics/hashes/outputinsidechild; review/prep/supervisortail
andpriorunknowncostadditional/notzero. ProducerSOURCE/ASTonly,noexecution/lock/push.

## Pre-execution v2 numerical admission correction
The v1 freeze874aaa31c0ae0d2c7bdd8f6cd8f74030753bf26ea8c8c73f35d8124b9bfb742b remains immutable and was never executed. No scientific modelvalues or boundary errors have been inspected. Prior source-only analysis: gamma192 isabout2.1e-14 forunitroundoff2^-53, multiplied bydotproductabsolute summands; Haar3-addition andhead/softmax errors alsoaccumulate. Thus toy3e-15 qualification isnot a wholeFIT errorbound. Beforefirstscience, parentfixed ONLYwholeFIT hidden/text/image closure admission to1e-12. This is aconservative engineering threshold, NOT a strictall-input/all-runtime IEEEproof, and iswellbelow original1e-10 nonregressiontolerance. Allqualifiedliteral3e-15/FD tolerances, normalizedpositive/residual/marginalguards, scientificgates, algorithms, budgets andtests remainunchanged. Anyv2 failure remains terminal/noretry; no later tolerance adjustment.
