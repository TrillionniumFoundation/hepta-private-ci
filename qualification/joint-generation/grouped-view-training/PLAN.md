# Fixed grouped-view training: A versus rowN versus groupN

SOURCE ONLY; independent static review and separate once-run admission required.
Original TEST closed. This adds input-view risk without changing reward/rho/anchor.
Group qualification RESULT15f2757cccb0dbba28affd91257c0f59f4ccc10d859a0a00eb85ba5ca80ad363
and complete wait4/source-review/saved-accounting are frozen prerequisites. Producer
saved accounting is not independent source review; parent performed that review.
Qualified grouped_risk.py and legacyutility bytes are unchanged and runtime-bound.

## Mechanism and exact sampler
Four freshly prepared source-masked FIT-source-supervised bases:folds0/1 xseeds103/107.
Each has A,rowN,groupN clones =>12models. Nominal202→32→two12heads/192pixeldecoder,
source-mode/inputmask/FITsource-label supervision identical across allarms.
Decoder300updates(.05),pretrain500sourceCE(.003,batch64),adapt300(.003,batch64).
No old weights/optimizer reuse. Source labels onlyownFIT traininggroups.

For eachbase, precompute exactly300batches with seed=modelseed+9000. Each selects
8distinct CONTENT groups outof130 without replacement; within each selects4distinct
variants outof6 without replacement, then emits each variant's full AND low view.
Thus64rows in8contiguous blocks of8, canonicalgroupids0..7. Bothchannels of a
variant are paired, not random independent channelchoices. Grouping is original
scene/instruction identifier, NOT targetclass. Same immutable schedule reused by
A,rowN,groupN. Runtime checks same contentgroup/target/command perblock, hence same
reward lookup pergroup. Original FIT1701/1702 and130/130paritysplit unchanged.

This optimizes entropic risk on a randomly selected4variant subset (8pairedviews),
not the exact complete6variantx2channel risk. Neither subsetriskgradient nor Adam
is claimed unbiased for full12viewrisk. A androwN also use this new sampler; oldiid
modeldigest reproduction is neither expected nor asserted. Equalstep/batch budgets
are not equalelapsedCPU guarantees; allnewbase prep and operations charged.

## Objective and anchor separation
Every arm computes all_terms rawA/rawN/alignedA/alignedN plus ordinaryraw/aligned
anchors, then aggregate_rows on alignedA(rho0,K8) and alignedN(rho1.5,K8).
Both aggregations are charged to everyarm. A selects rowA (bitwise equal togroupA),
rowN selects alignedrowN, groupN selects groupedalignedN; ALL add ordinary aligned
rowmean anchor.2 AFTER utilitygradient selection, never riskweight theanchor.
Group CE/gradient formula is the qualified K*softmax(-rhoCE) chain withrowgrad1/n.
Targets/rewards/groupmembership constant; noepsilon/floor/STE/clipchange.

Aligned CE uses ORIGINAL independent categorical output expectation after reward
pullback; this is not claimed to be an exact gradient of maximal-coupled serving.
Science serving stays original qualified normalized coupling plusFITtemperature.
This group objective does not silently fix/change that pre-existing train/service
law distinction. Newrisk addresses inputview/output variability, not guaranteed
accuracy or confidence improvements.

## Integration checks before FIT generation
37literaltests:28unchanged existing,6qualifiedgroup-risk fixtures,3newintegration
fixtures. Run all before ANY FITdataset generation or scientific counters.
New handcrafted2groupsx8views, partialcommand maps, sameR/command within eachgroup:
- Eight centralFD coordinates across bothheads for groupedalignedutility alone
  AND the full utility+.2ordinaryanchor loss, eps1e-6/tolerance3e-8.
- Independent flattened pulled-reward view/output CE parity(2e-15), exactgroupA
  rowA gradients and exact additiveanchor composition. Explicitly demonstrate
  nonuniform utilityweights must NOT be applied toanchor.
- Literal130groupx6variant identifiers test deterministic3batchsampler,8distinct
  groups/4distinctvariants/bothchannels/64rows,immutableinputs,invalidinventory.
No numerical fixtures run by sourceproducer. Literalmodel tests from prior suite
instantiate toy models, but no model payloads or scientific datasets are read.
Fixturework is additional to counters and fully included in actual childCPU.

## Global freeze, evaluation and original gates
All12models freeze, then24heads fit on ownFITtargetlabels with unchanged algorithm
[.125,8],24bisection/28evaluations; all24heads freeze before heldout regeneration.
Reuse previously studied3701/3702/3711/3712 noise and samegroups; NOT a newblind or
globallyunseen holdout. No seed/noise/model selection. Evaluate bothuncalibrated and
calibrated services and allbases. Preserve metrics/full/low/macro/all/partial.
Primary calibratedgroupN−A andgroupN−rowN each require all8unpooled contrasts pass
original5gates: macrofull/low partial rho>=.005; textmass,greedytext,jointsuccess
>=-1e-10; pixelMSE<=1e-10. Overall conjunction. Separately rowN−A and allthree
self-calibration comparisons;72contrasts including descriptive pooledviews, no
poolrescue. Keep negative outcomes; no ceiling-based threshold adjustment.

## Exact prospective scientific ledger
4newbases/12clones/0restores.1200decoder+2000supervised+3600adaptupdates.
Forwards4000pretrain+10800adapt+24FIT+32evaluation=14856batches;
256000+691200+18720+49920=1015840rows. Same source-maskcopy counts;
10158400instruction elements zeroed.1208decodecalls/14496images.
2FITdata/4heldoutdata/0TEST.3600alltermscalls/921600four-profileutilityrows.
1200schedulebatches/9600groupchoices/38400variantchoices/76800viewrows; schedules
reused across3arms.7200groupaggregations/460800rowvisits/57600groupCE values.
12FITservingcalls/18720tables;24heads/37440headrows;672NLLevals/1048320headrowevals.
56evaluationservingcalls/87360tables/12579840entries;174720CDFchecks;
37440calibratedinternalbasetables;74880argmax/74880supportchecks;
16baseprofile/12calibratedroundtrips. Runtime rejects inventory mismatch.

## Bounded execution proposal
Existing syntheticlock nonblocking/no replacement/no retry,CPU0/one numericalthread,
60CPU/180wall/512MiB/4MiB. Fully wait4 success/failure/killedchild andrecord actual
CPU/wall/RSS/exit. Alltests/newprep,schedule creation,masking,extraaggregations,
calibration/evaluation included. Historicalqualification .144417CPU additional;
source/review/supervisortail additional/nonzero. Memory-onlymodels; newbounded
RUN_ONCE outputs only. No originalartifact mutation, no publication byproducer.
