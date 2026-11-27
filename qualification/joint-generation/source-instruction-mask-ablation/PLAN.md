# Fixed instruction-mask causal ablation under equal FIT-source supervision

SOURCE ONLY; independent static review and bounded execution admission required.
Original replication RESULT44b0ff5ac6b1a103876bd4496120a52286d4f879aaf0c1abe0bb5a80df4804a9
and full-wait receipt remain immutable. Original TEST closed.

## Identified intervention and limits
Both arms have identical FIT-source labels, initialization, nominal202→32→two12heads
and learned192pixel decoder, supervised/adaptation schedules and serving law.
Masked SourceSceneModel is byte-identical to the qualified source arm. New visible
SourceInstructionVisibleModel has a distinct explicit mode/digest/clone and disabled
checkpoint IO. Both unified input entries validate and COPY all input. The sole
numerical input-path intervention is whether final10instruction dimensions are zero.
Visible retains them without any command-invariance guarantee. The10inactive versus
active encoder rows are the structural effect of masking, not a separately changed
network size. Identity tags and ledger instrumentation differ for correct binding
but do not alter numerical training. No extra labels/information unique to one arm.

Both pretrain on source-scene labels derived ONLY from own FIT training groups.
Neither serving path takes source labels, groupid, targetrenderer or hiddenmetadata.
Explicit commands remain intact outside the model for identical semantic transport.
Target-aligned anchor.2 and command-conditioned reward remain unchanged:
select_gradients(terms,'aligned',objective,.2), rho1.5, target labels in adaptation
and calibration. No raw_anchor substitution. Known12class decoder templates shared.

## Fixed matched design
Masked/visible x A/N x2folds xseeds103/107=16models/8newbases. Each base300decoder
updates(.05)+500source-supervised(.003,batch64); each clone300adapt(.003,batch64).
Same initialization seeds, sampled rows/channel draws and allfour utility branches
per fold/seed; no learned-state transfer. Source modes clone with exactweights,
newoptimizer, correct type/mode/digest. Both modes reject save/load beforeIO.

Original260FIT parity split130/130 per fold,6variants/group, FIT1701/1702,
heldout3701/3702/3711/3712 unchanged. These seeds/groups/noises are already studied,
not fresh or blind holdout; results identify this finite matched intervention,
not arbitrary domain generalization. No outcome-based split/seed/noise/arm selection.

All8masked model and4masked base digests must exactly reproduce the completed
replication's source-* boundedmetadata. No old model payload read or reuse. Abort
on mismatch rather than retune; visible baselines are fresh matched training.
All16models freeze before same ownFIT target-label temperature fitting[.125,8],
24bisection/28evaluations perhead. All32heads freeze before regenerating heldout
noise/evaluating anymodel. Allbase/model/source digests rechecked; no model selection.
Heldout source attributes enter only evaluator preservation metrics, not modelinputs.

## Fixed comparisons and gates
Primary masked-cal minus visible-cal separately forA andN; all16unpooled contrasts
must satisfy original5gates on partial-command full/low macro: rho>=.005;
textmass,greedytext,jointsuccess>=-1e-10; pixelMSE<=1e-10.
Fair calibratedN−A WITHIN masked and visible separately requires8unpooled contrasts
each. Overall=maskgate AND maskedNDUgate. Preserve self-calibration anduncalibrated
N−A;120total contrasts include descriptive pooled values, never rescue failures.
Extra source supervision is identical across arms: prior source-supervision gains
must not be attributed to mask without this contrast. Mask gains are not NDU gains.
Report every negative and any ceiling-limited gate failure without changing gates.

## Work/cost accounting
8newbases,16clones,0restores.2400decoder+4000supervised+4800adaptupdates.
22480forwardbatches/1533440rows;2416decodecalls/28992images.
2FITcalls/4heldoutcalls/0TEST;4800allterms/1228800utilityprofilerows.
16FITserving/24960tables;32heads/49920headrows;896NLLevals/1397760headrowevals.
80evalcalls/124800tables/17971200entries;249600CDFchecks;
49920calibratedinternalbasetables;99840argmax/99840supportchecks;
24baseprofile/16calibratedroundtrips.
Maskedcopy11240batches/766720rows/7667200zeroedelements;
visiblecopy11240batches/766720rows/0zeroedelements. Runtime asserts allcounts.
Scientific counters start AFTER31literaltests (28byte-exact existing +3new visible
tests); all fixturework remains inside whole-child measured CPU, not free.
New fixtures: initialparameter equivalence withdirect/masked models, inputretention
and independentcopy; exact forward/gradient equivalence to rawJointModel plus7central
finite differences (including instruction row); clone/type/mode/digest/optimizer
isolation and save/load refusal beforeIO. No fixtures executed by sourceproducer.

Existing synthetic lock/nonblocking/no replacement/no retry;CPU0/one numericalthread,
60CPU/180wall/512MiB/4MiB. Fullwait4 includes success/failure/kill and actualCPU/wall/
RSS/exit. Allnewprep,source labelderivation,inputcopy/masking,calibration/evaluation
included; equalupdates not equalCPU. Historicalresearch/source/review/supervisortail
additional nonzero. Boundednew RUN_ONCE only, memory-onlymodels, immutableoriginals.
