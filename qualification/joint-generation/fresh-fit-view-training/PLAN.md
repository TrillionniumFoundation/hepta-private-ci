# Fresh synthetic FIT view-stream intervention, matched A/rowN/groupN

SOURCE ONLY. Independent static review and separate bounded-run admission required.
Original TEST closed. Preserve staticgroup result80711beda39ef07251f7360e31c3ae536b729dcf866bbf637442ed0efb005f4d,
fullwait and frozenmetadata. Priorstatic result is historical, not a replacement
for the freshly trained strongA control. No staticarm rerun or gate adjustment.
Mechanism motivation: fixedFIT may be highly fitted andgroupN partlyrecovers versus
rowN; overfitting is a hypothesis to test, not an established explanation.

## Only new data stream
Keep4source-masked FIT-source-supervised bases/12A,rowN,groupN models, folds0/1,
seeds103/107, same300decoder/500pretrain/300adapt schedules and architecture.
Pretraining and FITtemperature calibration still use EXACT original6variants and
FITnoise1701/1702. All4base digests must reproduce oldstaticgroup pretraining;
no adaptedmodeldigest reproduction asserted, no oldweights read.

Same group_schedule seed+9000 chooses8distinct FITcontentgroups x4distinct variant
POSITIONS xfull/low=64rows. At adaptation only, each of32positions gets a fresh
synthetic source-scene observation instead of loading oldfixednoise image. The
variant position preserves pairedgroup/target scheduling, not the old pixelview.
Render source scene from correspondingFITgroup, drawuniform(.03,.25), independent
192normal scalars, clip[0,1], same2x2mean/repeat lowview and10instructiononehots.
Sourceattrs/target/instructions and recipe match originaldata; only newdraws.
Renderer is training-data preparation only, not generation/serving or modelinput.

Per-base fixednoise seeds19000+modelseed+100000*fold:
19103/19107/119103/119107. No search or adaptive generation. Precompute300steps
ONLY for currentbase; one immutable bytes-backed cache shared byall3arms, then
release before nextbase allocation. Sameuniqueview access and sharedprep charged
once perbase, not falsely billed independently to eacharm. No input depends on
model outputs, rewards or selectedarm. SHA at construction andbefore/after eacharm
checks exactcacheidentity (7hashpasses/base). Labels verified against fixedFIT
schedule targets everytrainingstep. Full/low observations paired exactly.

Synthetic source scenes are rerenderable; this adds38400unique noiseobservations
and real CPU/memory/hashcost. This is NOT free or generally available real-image
augmentation. Fresh sampled4iidcorruption group risk is not an unbiased estimate
of exactcontinuous-corruption entropic risk, nor unbiasedAdam. Fixed extra source
labels remain identical acrossA/rowN/groupN and derive only fromownFITgroups.

## Unchanged objective, evaluation and gates
Qualified all_terms4branches plusgroupA/groupN computed everyarm; chooseA,rowN,
groupN utilitygradient andadd ordinaryalignedrowmean anchor.2 separately. No risk-
weighted anchor, rho remains1.5 (A0), sameconstantreward/serving law/calibration.
Training remains originalaligned independent-output CE, not silently claimed exact
maximal-coupling serving gradient. All12models+24heads globallyfreeze before same
previously studied3701/3702/3711/3712 heldoutnoise. No newblind/globalgroup claim.
PrimaryfreshgroupN−freshA andfreshgroupN−freshrowN EACH need all8unpooled original
fivegates: partialmacro rho>=.005;textmass/greedytext/jointsuccess>=-1e-10;
pixelMSE<=1e-10. Overall conjunction. RowN−A,selfcalibration,pooled/allmetrics
preserved (72contrasts); no pooledrescue or thresholdchange, retain everynegative.

## Fresh helper fixtures before FIT generation
All37existing tests byte-exact plus3newmodel-free tests=40. Newtests use manually
specified groupcatalog and deterministic rendererSTUB, not actualdataset renderer.
Check same-seed equality/different-seed differentpixels, readonlycache andunchanged
inputgroups;64rows/8groups/4positions,bothchannels,exactlowdownsampling,pixelrange,
unchangedinstruction/targets,render/randomcounts; invalidseed/group/scheduleshape
rejected before renderer andinvalidrendereroutput rejected. No fixtures executed
by sourceproducer; allfixture work inside futurechildCPU, before scientificcounts.

## Work ledger and memory
Originalscientificledger unchanged:4bases/12clones;1200decoder+2000supervised+
3600adaptupdates;14856forwardbatches/1015840rows;same sourcecopies/10158400zeros;
1208decodes/14496images;2FIT/4heldout/0TEST;3600allterms/921600utilityprofilerows;
1200schedulebatches/9600groupchoices/38400variantchoices/76800schedulerows shared
3arms;7200groupaggregatecalls/460800rowvisits/57600groupvalues;
24heads/672NLLevals/1048320headrowevals;56evalcalls/87360tables/12579840entries;
174720CDFchecks;37440internalcalibratedtables;74880argmax/supportchecks each;
16baseprofile/12calibratedroundtrips.

Additionalfreshledger:38400renderer calls/observations,38400uniformdraws,
7372800normal scalars,76800pairedview rows. Perbase cache shape300x64x202float64
plus300x64int64labels:31180800payload bytes. At construction originalmutable+
bytes-backedcopies peak payload <=62361600bytes, excluding object/workspace/runtime
overhead; measured wholechild maxRSS is authoritative, not this theoreticalbound.
Only1basecache retained, no all4 simultaneous. Hashpasses28 total; each hashes
31180800payload bytes PLUS exactcanonical seed/shape header length. Runtimeledger
computes expectedtotalbytes for all4seeds, including6before/afterguards perbase.
Freshprep CPU includesdraws/render/array/copy/initialhash; guardCPU separate.
AdaptationCPU explicitly stops BEFORE afterguard; sharedcost not duplicated in
perarm timings. Other source/data/prep/loop/timing overhead remains in wholechild.

## Execution boundary
Existing syntheticlock/nonblocking/no replacement/retry;CPU0/one numericalthread,
60CPU/180wall/512MiB/4MiB, completewait4 actualCPU/wall/RSS/exit includingkill/failure.
Allnewprep/uniqueinformation costs charged; equalupdates not equalelapsedCPU.
Historicalstatic16.69671CPU pluspriorqualification/research separately nonzero;
source/review/supervisortail additional. Memory-onlymodels, frozeninputs/sources,
boundednewRUN_ONCE outputs. No numerical execution, modelpayload access, locks or
publication bysourceproducer. Independent review before any scientificrun.
