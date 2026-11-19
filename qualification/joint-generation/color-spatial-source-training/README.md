# Color × joint-spatial prior: original scientific gates failed

**CSA−directA:0/8; CSA−fullfactorA:0/8. Overall false.**

The unique fixed3×4 prior separatescolor fromjointshape-position, rather than
full3×2×2 factorization. It was motivated by renderer source constructing a spatial
mask thenassigningcolor; that is not posteriorindependence evidence. The newprior
preserves four-state spatialdependence but removescolor-spatialcorrelation. Output
freedom is5 versusfullfactor4/direct11; sameparameters/init notsamefunctionclasses
or initialpredictions. No otherpartitions were swept. Allarms train additiveA:
these results are not a NDU training success or failure attribution.

Threeworkmatched arms each own four source-supervised commandblindbases,folds0/1,
seeds103/107. Fixed300decoder/500sourceCE/300adapt steps, sameoldstatic64sampler,
A+.2ordinaryanchor, oldFITcalibration andoriginalreward/fivegates. Everyarm computes
threeheadlaws, bothqualifiedpullbacks andthreeparametergradientdicts, selectsone.
Discardedotherdicts use selectedlawupstreamg and are computationalauxiliary, not
otherobjectiveestimates. Naturaldeploymentcost cannot be inferred fromthis matching.

Tripleinitialtensors/pairdecodersequal; all12actualdecodedtext/image maps canonical.
Strongdirect ANDfullfactor historical8bases/8adaptedmodels/completeoldmetrics/
FITrecords/profilekeys/datasets matched exactly. All12weights then24heads froze
before previouslystudied noise regeneration. OriginalTESTclosed, knownFITcatalog/
noise exploratory, notfreshglobalgroup evidence; no model/seed/thresholdselection.

## Fixed whole-partial scientific comparisons
Calibrated originalmeanrowCE differences, partialcommands macro(full,low):

| Fold | Seed | Noise | CSA−directA | CSA−fullfactorA | Five-gate pass vs direct / full |
|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | +0.000206234 | -0.000823646 | False / False |
| 0 | 103 | 3702 | +0.001614167 | +0.000072865 | False / False |
| 0 | 107 | 3701 | +0.004202763 | +0.000065989 | False / False |
| 0 | 107 | 3702 | +0.000308429 | +0.000401354 | False / False |
| 1 | 103 | 3711 | -0.001123178 | -0.002474564 | False / False |
| 1 | 103 | 3712 | +0.003039289 | -0.001004701 | False / False |
| 1 | 107 | 3711 | +0.004448520 | -0.000335534 | False / False |
| 1 | 107 | 3712 | +0.002804508 | -0.001006483 | False / False |

AgainstdirectA seven CE differences arepositive, maximum+.004448520 belowunchanged
+.005. AgainstfullfactorA onlythree CE differences arepositive. Everyprimaryfails.
CS losing tofullfactor does NOT causallyprove preserving spatialcorrelation isbad:
theprior changes a constrainedlearnedrepresentation and optimization, not anisolated
observedcorrelation treatment. Keepstrongcontrols andalloldfailures, nopartition or
threshold rescue. All72contrasts/fullmetrics/basefullmetrics are retained inSUMMARY.

## Descriptive strata are not replacement gates
Predeclaredcolor_only andother_partial are disjointnonempty andpartition original
partialcommands. SUMMARY preserves everymodel/base/service/full-low-macro/noise/
metric reduction androwcounts separately inmechanism_strata, without adding fields
to oldresults schema. No subgroup wasselected forreporting orused torescuegate.
Same-rawpolicy transportalgebra predictsCS/full equalitywheneitherspatialaxisisset;
trainingchangesrawpolicy, so it doesNOT predict empiricaleffectsonlycolor-only.
ForCS−fullfactor, descriptivecolor-only CE ispositive3/8 andnegative5/8;
otherpartial ispositive2/8 andnegative6/8. Neither pattern supports a spatial-
preservationcausal rescue.
432extra scalarreductionrecords androw/attributevisits/CPU arecharged, withzero
extra model/servingcalls. They are descriptive, notcausalevidence ornewvalidation.

## Validation and total cost
55tests passed beforeFIT, including49toyinitializations/23toyupdates, separately
countedinsidechild. SeparateCSqualification17tests/14toyinitializations cost.347780
CPUseconds; priorfullfactorqualification.258624CPUseconds. Currentfullywaitedchild
48.138351CPU seconds/48.629295762wall seconds,97648KiB RSS. Prospectivelyexpanded
60CPU/180wall/512MiB/4MiB,CPU0singlethread/sharednonblockinglock/no retry.
Thelargertotalcost includes3arms,12ownbases, tripleauxiliarycomputation andnewstratum
reductions; it is not equaloldtwo-armspend orfreeinformation. ActualCPU andwall are
separatelyreported; equaloperationcounts neednot implyequalclockcost.

3600decoder+6000supervised+3600adaptupdates;22872rawforwards/1552800rows;
3624decodes/43488images. PERrepresentation:7624rawforwards/517600rows;
fullprojection ANDCSprojection each15248calls/1035200rows; fullpullback ANDCS
pullback each6400calls/409600rows; raw/full/CSparamdicts each3200/204800rows.
AllphaseWORK, actualbase/arm/FIT/eval/data/strata timings, wholeSHA, masks, serving/
NLL/counterledger andfullwait4receipt preserved. Priorunknown/review/supervisortail
costs remain additional/notzero. No naturaldeploymentspeed ororiginalNDUclaim.

## Portable sixfile package
Exacttriplewrapper/test andfrozenPLAN plusREADME/SUMMARY/VALIDATION; nounrestricted
runner, privateinputs, runtimepaths, weights, merge or deployment. Dependencies are
published source_scene, factorized-source, color-spatial-source and originalmodel/
utility/aligned/transport/control modules; put them onPythonpath forliteraltests.
Alltestinputs arehandcoded. Complete scalarprofiles/modelrecords/digests/barriers
remain, notmodelpayloads. Independentreview success validatesexecution/accounting,
not scientificgates. Latermechanisms arepost-result hypotheses, nottunedrescues.


## Lossless evidence storage

The complete original SUMMARY is stored as `SUMMARY.json.gz` to meet the repository blob limit. No metric or failed gate was removed. From `qualification/joint-generation`, run `python3 restore_evidence.py` to verify all four compressed summaries, or `python3 restore_evidence.py --output /path/to/new-output-directory` to restore exact original JSON files. The output directory must not already exist. `compressed-evidence-manifest.json` binds compressed and original SHA256 hashes and byte counts. This command verifies evidence only and does not run models or training. Old commit history remains unchanged.
