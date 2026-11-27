# Same-count independent FIT-view calibration: exact static/fresh A controls

SOURCE ONLY; independent static review and bounded once-run admission required.
Original TEST closed. Temperature-chain practical-domain failure staysimmutable;
newcalibration onlyuses existing forward/NLL APIs, notfixed_chain derivatives or
relaxedguards. No NDU training/success claim; priorNDU negatives remainunchanged.

## Exact additive training controls and shared cost
4shared source-masked bases:fold0/1,seeds103/107, original300decoder+500sourceCE.
Each has staticA andfreshA clones:8models,each300updates×64rows,originalsame
group_schedule(seed+9000),ordinaryalignedanchor.2,lr.003. Everyarm still computes
all_terms4branches plusgroupA/groupN auxiliaries to preserve historicalarithmetic.
Onlyadditive gradient selected. Inputs/source labels/modelcapacity/optimizer and
known12decoder templates unchanged. Same4bases reused ratherthan twicecharged.

Static usesold6FIT variants. Fresh usesbyte-exactfresh_views seeds19103/19107/
119103/119107 and38400observations/76800pairedviews. Currentbasecache shared with
its singlefreshA arm thenreleased; construction+before/after hashes=3passes/base.
StreamSHA must matchhistorical fresh stream. All4base and8trainedA digests must
exactly match oldfrozenmetadata. No modelpayload restore or checkpoint saves.

Historicalstatic RESULT80711beda39ef07251f7360e31c3ae536b729dcf866bbf637442ed0efb005f4d
andfresh RESULT1cd99d639a21475cbdb1aaa65454e3bbebf29698317cb345d704a24b310fa682,
fullwaitreceipts/frozenmetadata are exactsource bindings. AlloldFITcalibration
records/profilekeys, completeuncal/oldcal modelmetrics,base metrics andoldFIT/heldout
manifests must EXACTLY reproduce. Mismatch aborts; no relaxedtolerance/selectedcells.

## New intervention: calibration view reuse, NOT doubled fit size
Onlyafter ALL8models freeze, create one readonlynewcal dataset perfold fromthatfold's
130FITcontentgroups,6newnoise variants/group. Fixedseeds5701/5702, nosearch. Same
SOURCE render,uniform(.03,.25),192normal scalars,clip,2x2mean/repeat lowview,command/
target recipe. Additional1560observations/3120pairedviewrows across2folds. Shared
perfold static/fresh×2seeds, preparationcharged once. No newcaldata in modelupdates.
Source is synthetic rerenderable FITscenes: extrauniqueinputinformation andgeneration
cost are real, not free/generalreal-imageaugmentation.

Oldprofile fits ONLYold780rows×full/low=1560rows/head; newprofile fits ONLYnew780×2
=1560rows/head. They are separatefits, NEVER concatenated into3120rows/head. Same
[.125,8]/24bisection/28evaluation algorithm forbothheads/allmodels. Two profiles/model
=>32heads total. Both static/fresh receive equaladdedcalibrationbudget andnewviewcache.
No heldout-driven temperature choice. Ifold/newtau coincide, samegenerationprofilekey
is correct; provenance differs but servinglaw doesnot. Do not force artificialkeys.

RequireoldFIT/newcal completegroup/label/command equality andfullinputhash disjointness;
full/low instruction equality too. Newseeds define a separatefixedpseudorandom stream,
NOT proof ofstatistical independence. We doNOT claim an exhaustive newcal/fresh-
training38400draw overlap check; no per-observationfreshhash inventory is retained.
New per-fold arrays readonly; old arrays unchanged with historical controls checked. Sharedgeneration costs separate; uniqueinformational
budget across theexperiment grows onecalibrationviewset butperfit samplecount same.

## Barriers, unchanged evaluation and prospective gates
ALL8models frozen ->all16old/newprofiles (32heads) frozen ->regenerate previously
studied3701/3702/3711/3712 heldoutnoise. No newblind/globalgroupclaim. Evaluate8models
uncal/oldcal/newcal plus4bases; same11metrics full/low/macro,all/partial. Historical
oldmetrics/profilekeys/datasets checkedexact beforedrawing newcomparisons.
Primarynewcal−oldcal forstaticA:8unpooledcontrasts; sameforfreshA:8; contentcontrol
freshA_new−staticA_new:8. Each mustpass ORIGINAL5gates: macrofull/low partial
CE>=.005; textmass,greedytext,jointsuccess>=-1e-10; pixelMSE<=1e-10. Overall all24.
Keepoldfresh−staticoldcal, newselfcal andoldselfcal versusuncal forbothmodelclasses,
allnegatives/pooledviews.96contrasts total:36primarywithpooled+12oldcontent+
24newselfcal+24oldselfcal. Additionally12descriptiveinteraction records (fold/seed/
noise includingpooled), allmetrics/channels/populations: (fresh_new−static_new)−
(fresh_old−static_old), algebraicallyfresh(new−old)−static(new−old). gate=null,
onlysaved-evaluation scalars,noextramodelcall,no causal/significance inference or
scientificgate rescue.96contrasts/24primary remainunchanged. Poolingneverrescues. No thresholds/τ/seeds selection.
Calibration/content gains cannot be calledNDU gains; boundsaturation may produce
nochange andfail originalmargin, which is a validnegative result, not reasonretune.

## Literal fixtures and exact work ledger
Original40tests byte-exact +3newmodel-freetests=43, beforeanyscientificFIT. Newtests
usemanual130groupcatalog andrendererSTUB:fixedseeddeterminism/differentbranch,
readonlyarrays/inputimmutability; all130×6targets/instructions/ranges/exactlowview/
renderer/countinventory; invalidfold/seed/group/shape rejection. Noactualdataset
renderer duringliteraltests. Fixtures unexecuted bysourceproducer; futurechildCPU
includes allfixturework, excludedfrom scientificcounters below.

4bases/8clones/0restores;1200decoder+2000supervised+2400adaptupdates.
11256forwardbatches=4000pretrain+7200adapt+32old/newFIT+24evalrawcached;
779200rows=256000+460800+24960+37440. Sameinputcopycount/7792000zeros.
1208decodecalls/14496images.2oldFITcalls/4heldoutcalls/0TEST.
2400allterms/614400utilityprofilerows;4800groupaggregations/307200rowvisits/
38400groupvalues.1200schedulebatches/9600groupchoices/38400variantchoices/
76800schedulerows reused2arms (153600actualadaptrows).
16FITservingcalls/24960tables;32heads/49920headrows;896NLLevals/1397760headrowevals.
56evalservingcalls/87360tables/12579840entries;174720CDFchecks;
49920calibratedinternalbasetables;99840argmax and99840supportchecks;
12baseprofile and16calibratedroundtrips.
Freshtraining38400render/uniform/observations,7372800normals,76800pairedviews;
12streamSHA passes/374170026bytes inclheaders. Onecurrentbasecache31180800payload
bytes;construction two-copy payloadbound62361600 (notRSSbound), thenreleased.
Newcal2datasets/1560render/uniform/observations/299520normals/3120viewrows and1560
inputSHA hashes. Perfoldreadonlypayload2527200bytes,2foldtotal5054400; temporary
copyboundseparatefrom measuredRSS. AllPythonSHA256construct/updatebytes/copies are
counted globally, includingtests/model/profile/source/newviewhashes; no invented
constant total. Scientificworkinventory runtimeasserted exactly.

## Complete costs and resource limits
30CPU/90wall/512MiB/4MiB,CPU0/one numericalthread,existing syntheticlocknonblocking,
no replacement/retry. Fullwait4 records actualCPU/wall/RSS/exit. Sharedbaseprep once,
freshstreamprep/guards,newcalgeneration once/fold, permodelold/newFITfitting and
serving timings separately recorded. AdaptCPU excludesfreshhashguards to avoid
thatdoublecharge; otherinterleaved source/hash/bookkeeping overhead insidewholechild.
Stage timings are descriptive, not an exhaustive additive partition oftotalCPU.
Equalupdates andaddedfitbudgets doNOT implyidenticalactualCPU. Historicalstatic
16.69671CPU/fresh18.582851CPU andpriorresearch/source/review/supervisortail additional,
notfree. Frozenoldsource/results unchanged; memory-onlymodels,boundednewRUN_ONCE.
No numerical execution/import/modelpayload/lock/push bysourceproducer.

## Documentation-only v2 revision
The v1 candidate was never executed and remains immutable. Its FREEZE.json SHA256 is `57fd4676784eebd0c7730524f2391f3270fee85532aa9e3d45c4c9907a198175`. This revision corrects only the old FIT-array mutability description: new calibration arrays are bytes-backed readonly; original group_data arrays retain their original writable representation. All Python sources, tests, algorithms, budgets, gates, INPUTS and external historical/prerequisite bindings are byte-identical to v1.
