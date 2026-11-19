# Frozen-temperature FIT directional preflight (source only)

Implements the parent's frozen PLAN_DRAFT.md; independent source review and bounded
once-run admission still required. No numerical execution byproducer. This is a
FIT engineering launch screen, NOT a scientific benefit result or changedfivegates.
Qualified chain RESULT0cb9ade6d8af67353ea3b4d2e0e7eb9ea61c348a49d38a11068f9ba4f2a3d7b6,
fullwait, independent source/saved reviews and sourcefreeze are bound inINPUTS/freezes.
Before anyscientificFIT/model, rebuildqualificationliteral(.5,2)profile andrequire
exactmetadata/key equality withsavedresult, includingruntimeprecision/domain.
fixed_chain andall26qualifiedfixtures/dependencies byte-exact. No oldsource mutation.

## Fixed stages, no selection
Rebuild4source-masked bases (fold0/1,seeds103/107), original300decoder+500source-label
pretraining, originalFIT6variants1701/1702,lr.05/.003/batch64. All4historicalbase
digests required; no restore. Fit2temperatures/base on complete780FITrows xfull/low,
unchanged[.125,8],28evaluations/head. All4bases AND8temperatures freeze together.
No sentinel scoring, optimizer direction orholdout generation beforethatbarrier.

Seed29000+modelseed+100000fold selects16distinct partial-command FITcontentgroups
(1or2explicitattributes) without replacement. First8gradientgroups,second8sentinel.
Gradient=4distinctof6variants/group xfull/low=64rows. Sentinel=all6xfull/low=96rows.
No targetclassgrouping/model-adaptive selection. Sentinel groups disjoint from
currentgradientgroups but used inpretraining/FITcalibration: NOT model-unseen/blind.

Five fixed utilitydirections perbase, allplusordinaryalignedrowmean anchor.2:
independentA,independentN,coupled-tau1N,newfixedtauA,newfixedtauN. rho0/1.5 andoriginal
reward unchanged. Compute ALL20parameter gradients across4bases BEFORE anyAdam
orstep evaluation. Allcoupled auxiliary calls are charged; no omission orselection.

Then eachdirection uses oneprivatefresh-moment originalAdam clone,lr.003/normclip5.
Record actual fullparam displacementnorm. Separatebaseclone gets thatdisplacement
scaledby min_all5norm/norm_i, neverenlarged. Refusezero/nonfinite norms, nofallback.
Normmatchedclones are explicitparameterperturbations, NOT Adam steps. Equalglobal
parameter L2 norm controls onlydisplacement size, notfunction-space step orAdam
unbiasedness. Recordactual
postaddition norm andtarget (rounding tolerance1e-12*max(1,target)), no gradient
inner-product guarantee. All40native/normmatched clones freeze before ANYsentinel
score. No sequential training, checkpoints, optimizercarryover ormodel choice.

## Evaluation and predeclared screen
Forbaseandall10steps perbase, fixedbase tau is rebound to eachmodelidentity; never
refit. Use originalcalibratedCDF service/reward. Full/low/macro reportCE,textmass,
greedytext,jointsuccess,pixelMSE,ordinaryanchor andminimized -CE+.2anchor. Preserve
all40outcomes, allbase-relative deltas andalladverse metrics. Derivedsmoothgraph is
not derivative ofroundedinstructions orFITrefit algorithm. Decoder remainsfixed.

Strict launch screen ONLY: forbothnative ANDnormmatched, fixedtauN exceeds EACHof
fouralternatives in EACHof4bases bymacroCE>1e-10, textmass>=-1e-10 andMSE<=1e-10;
meanCEdifference over4bases >1e-8 forEACHkind/comparison. All32perbase plus8mean
checks conjunctive. Failure closes thisparticular large-run launch; no direction
selection,taurange/threshold/seed expansion orweakerbaseline substitution.
This screen is not a significance test andfailure doesnot prove thewhole
temperaturefamily mathematically invalid. Originalscientific +.005/fivegates
unchanged andexplicitly NOTapplied/passed here.
NoVAL/TEST data generated. Latertraining needs separatefreeze/review/admission.

## Exact domain refusal behavior
Any lossdomain refusal aborts thewholecampaign. Allgradients are globally before
Adam/sentinel, so a refusal there leaves0directionupdates/0sentinelevaluations.
One predeclared WHOLE64row forwardaggregate diagnostic thenrethrow; neverrowselect.
Oldcoupled-tau1 failure diagnoses oldnormalized._law withsamefixedmaps. Newfixedtau
failure diagnoses newfixed_chain._law withsameprofile/commands. Recordgraph,positive
tierowcount,minresidual,zero-denominatorcount,maxrelativebalance ondefineddenominators;
ifdiagnosticitself refuses, recordattempt/failure andstop, nosecondcall.
Noepsilon,τchange,floorrelaxation,filtering orretry. Keepattempt/completed counters
andfailureprogress. Sentinel/service orotherinvalidstate refusals alsoabort; norescue.

## Prospective successful-path ledger
4baseinitializations,40clones,0restores.1200decoder+2000supervised+20nativeAdamupdates;
20manualperturbations assign160parametertensors/195680scalars. Eachnative ANDmatched
actualdisplacement measures160tensors/195680scalars. Model has9784scalars incldecoder.
Forwards4000pretrain+8FIT+24direction+44sentinel=4076; rows256000+6240+1536+4224=268000.
Same sourceinputcopy4076/268000rows,2680000instructionzeros.1208decodecalls/14496images.
2FITdatasets,0VAL/TEST.4FITbase-servingcalls/6240tables.8heads/12480headrows,
224NLLevals/349440headrowevals.4FITtemp roundtrips+44sentinelrebound=48.
4gradientbatches/256rows,4all_termscalls/1024fourprofileutilityrows;
4oldcoupledattempts/completions256rows,8newfixedattempts/completions512rows;
20parametergradientcalls.4samplers/32gradientgroups/32sentinelgroups.
44sentinelmodel/servingcalls,4224outputs and4224internalbasetables;
8448extraCDFmarginalchecks and4224ordinaryanchorrows.0failurediagnostics on success.
Runtimeasserts these counts. Onfailure report actualprefix ratherthan completedplan.

AllPython hashlib.sha256 constructors/updatebytes/copies are transparently counted
frombeforefreezecheck through26old+2newliteraltests,model/profilekeys/sourcechecks.
Modeldigest calls additionally counted aftertests. No fixednumber invented for
nestedprofile hashing; reportmeasuredcounts. Supervisorhashing outsidechild remains
additional. Hashwrapper preserves digestvalues; originalsource/helper code unchanged.
New2model-freefixtures testfixedpartial sampler/disjointvariants/channels/determinism/
inputimmutability andnormmatch no-enlargement/actualnorm/invalidshape/nonfinitezero.
All28tests run BEFORE scientificFITgeneration andscientificcounters; SHAcounts and
wholechildCPU include them. No actualmodel/datasetpayload access inliteralfixtures.

## Resource controls
10CPU/45wall/512MiB/4MiB,CPU0/one numericalthread,existing syntheticlocknonblocking,
no replacement/retry. Fullwait4 includes success/failure/killedchild withactualCPU/
wall/RSS/exit. Allnewprep,FITfitting,20gradientdirections,20nativeAdam,20perturbations,
all40outcomes+4baseevals,hashes/diagnosticcost insidechild. Completedbase/FIT and
FITdata-generation cost snapshots are written atglobalbase/tau barrier andfailure;
failure also records currentphase/direction elapsedCPU whenknown, remainingcost
inwholechild notzero. Qualification1.007076CPU
andearlierresearch/source/review/supervisortail additional/nonzero. Memoryonlymodels;
newboundedRUN_ONCE metadata/JSON only. Historicalnegatives remainunchanged.
