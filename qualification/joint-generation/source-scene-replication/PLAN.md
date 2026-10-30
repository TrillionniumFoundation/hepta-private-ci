# Fixed source-scene new-initialization/new-noise replication

SOURCE ONLY; independent static review and bounded-run admission required.
Original source-decomposition result and negative NDU conclusions are immutable.
Bind original RESULT062f20e851a412bcdf06bca7ad5f9e3fe770df5c55bf5dc640d99151fdde448e
and full-wait receipt as historical evidence, never as model weights.

## Fixed change, all else unchanged
New model seeds103/107, chosen once without search. Original FIT group parity
partition130/130 and FITnoise1701/1702 unchanged. New heldout noise fold0=3701/3702,
fold1=3711/3712, fixed before generation. Newwrapper rejects any other seed, wrong
fold, bool/float/string seed or variant count; old group_data remains byte-exact.
Wrapper reuses original partition and identical rendering/corruption recipe;
only the fixed heldout seed domain differs. Literal API tests exercise rejection
before partition/noise generation. No successful noise call before global freeze.

Historical groups were already studied and informed the mechanism. This tests
new model initialization and new corruptions on the SAME group allocation, not
new global groups or a fully blind scientific holdout. Original TEST stays closed.
No seed/noise/split/model selection, no parameter scan, no pooled rescue.

## Model, supervision and matched controls
Same direct/source x A/N x2folds x2seeds=16models and8newbases. All fresh direct
baselines use new seeds; prior exact-digest reproduction assertion is intentionally
removed because different initializations cannot reproduce old models. No old
weights or optimizer state restored. Equal index/channel draws withinfold/seed
between mechanisms/A/N, nominal capacity and300decoder+500supervised+300adapt
schedule unchanged.300decoder(.05),500supervised(.003),300adapt(.003,batch64).

SourceSceneModel and five source fixtures are byte-identical. Explicit mode
source-scene-FIT-supervised-v1; unified input copies and zeroes last10instruction
dimensions for BOTH forward/gradients. Nominal202→32→two12heads unchanged but
10inputrowsinactive means effective capacity changed. Source pretraining adds
FIT-only source labels from that model's training groups; direct uses targetlabels.
This additional supervision is disclosed, not called a pure NDU effect.

Both retain original select_gradients(terms,'aligned',objective,.2), rho1.5,
true target labels and transported semantic reward/anchor. No raw_anchor switch.
Correct source scenes transport to targets; serving only consumes observedpixels
and requestcommands, not source labels/groupid/renderer. Heldout source attributes
are evaluator-only. Decoder known12templates unchanged. Source digest/mode/clone
isolation retained; source save/load reject beforeIO. All models memory-only.

All16models freeze BEFORE fitting all32heads on ownFIT targetlabels, same post-
transport NLL algorithm[.125,8],24bisection/28evaluations. All32heads freeze BEFORE
any newheldout noise generation/evaluation. Model and source digests rechecked.

## Original gates and complete reporting
Primary calibratedsource-A−direct-A and source-N−direct-N: all16unpooled contrasts
must pass original5gates. Within-source faircalibratedN−A: all8unpooled contrasts
must pass; directN−A separately reported. Overall=mechanism AND sourceNDU.
Self-calibration and uncalibratedN−A controls retained.120contrasts include pooled
values only descriptively. Originalmacrofull/low partialcommand thresholds:
rho>=.005; textmass,greedytext,jointsuccess>=-1e-10; pixelMSE<=1e-10.
No gate relaxation near saturation, no positive-only selection. Mechanism gains
cannot be renamed NDU gains. No significance claim for dependent finite views.

## Exact prospective ledger
8newbases,16clones,0restores.2400decoder+4000supervised+4800adaptupdates.
22480forwardbatches/1533440rows;2416decodecalls/28992images.
2FIT calls,4newheldout calls,0TEST.4800allterms/1228800utilityprofilerows.
16FITserving/24960tables;32heads/49920headrows;896NLLevals/1397760headrowevals.
80evalservingcalls/124800tables/17971200entries;249600CDFchecks;
49920calibratedinternalbasetables;99840argmax and99840supportchecks;
24baseprofile/16calibratedroundtrips. Source mask11240batches/766720copiedrows/
7667200zeroedelements. All counts runtime asserted after28literaltests.
The26existing tests unchanged plus2new API rejection tests run before scientific
instrumentation. Their work is not in scientific counters but fully inside childCPU.
Extra source-label derivation, all newprep/copies/calibration/evaluation charged.

Existing synthetic lock, nonblocking/no replacement/no retry;CPU0/one numerical
thread,60CPU/180wall/512MiB/4MiB. Complete wait4 records success/failure/kill,
actualCPU/wall/RSS/exit. Equalupdates NOT equalelapsedCPU. Historicalresearch,
source/review and supervisorfinaltail additional/nonzero. New outputs only
RUN_ONCE; frozen source and original artifacts immutable. No numerical execution,
payload reads, lock operations or publication by source producer.
