# Fixed source-scene decomposition versus exact direct controls

SOURCE ONLY; independent review and bounded execution admission still required.
Original TEST remains closed. No numerical execution by source producer.

## Mechanism
Explicit source-scene-FIT-supervised-v1 retains nominal202→32→12x2 model and
learned192pixel decoder. Unified _input validates and COPIES input, then masks
last10instruction dimensions for every forward and gradient. Original inputs and
commands remain intact for external transport. Nominal parameter count unchanged,
but10encoder rows inactive: effective capacity changes. This is not capacity parity
in the stronger functional sense.500supervised steps use source-scene labels parsed
ONLY from this model's FIT training groups. This adds semantic supervision and
changes representation, not a pure NDU intervention or free serving information.
Direct controls retain original JointModel and500target-label supervised steps.

Both mechanisms retain select_gradients(terms,'aligned',objective,.2), true target
labels/command-conditioned utility andrho1.5 in300adapt steps. The anchor is the
transported target-semantic anchor, NOT raw latent target CE; correctly predicted
source scenes map to correct targets. Explicitly specified attributes collapse
under transport and need no raw-source anchoring on those axes. No raw_anchor swap.
Serving sees only observed pixels and explicit request words through qualified
transport/coupling/calibration. No source labels/groupids/renderer enter serving.
Evaluator-only source-attribute preservation metrics may read heldout metadata;
these never feed model training, predictions or temperature fitting.
Known12class templates remain decoder supervision; no unseen-class/template claim.

## Fixed matched trial
2mechanisms x A/N x2folds xseeds71/89=16models,8newbases. Each base300decoder
updates(.05)+500supervised(.003,batch64); each clone300adapt(.003,batch64). Same
index/channel draws across mechanisms and A/N within fold/seed; allfour raw/aligned
terms computed equally. New initialization/preparation fully charged. No shared
learned parameters/optimizer across mechanisms or folds. Source clones retain type,
mode and exact weights but reset optimizer. Tagged digest separates identical
parameter bytes from direct mode. Source save/load reject BEFORE IO; no format or
old-checkpoint compatibility. No model payload saves/restores.

Unchanged group_data: original260FIT catalog parity split130train/130heldout,
6variants/group. FITnoise1701/1702; heldout2701/2702/2711/2712. These groups AND
noise realizations were previously studied and motivated this mechanism: NOT new
blind holdout, globally unseen data or original TEST. Per-new-model group separation
remains; no allocation/seed/noise selection. All8direct model and4direct base digests
must reproduce bounded old ALL_MODELS_FROZEN metadata exactly; abort on mismatch.

All16models freeze before calibration; all32heads use own training-fold TARGET
labels after transport, qualified NLL calibration[.125,8],24bisection/28evaluations.
All calibrators freeze before regenerating heldout observations/evaluating models.
No fold/seed/model selection or fallback.

## Decisions
Primary: calibrated source-A minus direct-A and source-N minus direct-N. Separately
fair calibrated N-A WITHIN each mechanism. Source-supervision/architecture benefit
is NOT NDU benefit. Preserve self-calibration, uncalibrated N-A, allnegative results.
Original5gates on partial-command full/low macro: rho>=.005; textmass,greedytext,
jointsuccess>=-1e-10; pixelMSE<=1e-10. Mechanism gate requires all16unpooled primary
contrasts; each within-mechanism NDU gate all8unpooled contrasts. Overall joint
claim=mechanism AND source-NDU. Self-calibration is separately reported, not selection.
120contrasts include descriptive pooled results; pooling cannot rescue failed arms.
No independence/significance claim for reused finite groups/noises.

## Work/cost ledger
8bases,16clones,0restores. Updates2400decoder+4000supervised+4800adapt.
22480forward batches/1533440rows;2416decode calls/28992images.
2FITdata calls,4heldout calls,0TEST.4800allterms calls/1228800utilityprofile rows.
16FITserving calls/24960tables;32heads/49920headrows;896NLL evaluations/
1397760head-row evaluations.80evaluation calls/124800tables/17971200entries;
249600CDFmarginalchecks;49920calibrated internal base tables;99840argmax and
99840supportchecks.24base-profile and16calibrated roundtrips.
Source mask11240batches/766720copied rows/7667200zeroed elements.
Counters cover model/scientific work, installed after26literal tests. Literal
work (21existing+5new) is additional and included in measured whole-child cost.
Tests prospectively check input immutability/command invariance for forwards and
gradients, central finite differences encoder/bias/bothheads including inactive
encoder row, clone/type/mode/digest/reset isolation, save/load rejection beforeIO,
and explicit mode/dimensions. Tests unexecuted by producer.

Existing syntheticlock nonblocking/no replacement/retry;CPU0,one numericalthread,
60CPU/180wall,512MiB/4MiB, completewait4 including failure/killed child. All new
prep/calibration/evaluation/copies inside child CPU; equal updates NOT equal runtime.
Historical research/source/review/supervisor tail additional nonzero. Source/evidence
hashes frozen; memory-only models and bounded new RUN_ONCE outputs only.
