# Fixed Haar timing, A-only: RR versus RH versus HH

SOURCE ONLY prospective experiment. Prior adaptation-only HaarA improved all five
metric directions in eight strata but failed every original .005 CE gate; HaarN
then lost to HaarA in all eight CE/textmass/joint/MSE comparisons. The adaptation
coordinate rescue of NDU is closed. This new test moves the SAME unique Haar
coordinate system into the previously untested 500-step supervised optimization
phase. Diagonal Adam is not rotation covariant, so pretraining can change learned
content trajectories despite identical initial functions. This is limited evidence
for a stage intervention, not a prediction of benefit or a NDU success claim.
No new basis, dimension reduction, factor prior, risk reweighting or parameter search.

## Three predetermined paths and strong controls
RR: 500 source-CE raw coordinates, then300 A raw coordinates.
RH: the SAME pretrained raw base, then300 A Haar coordinates (old control).
HH: 500 source-CE Haar coordinates, then300 A Haar coordinates.
Folds0/1 and seeds103/107, original 130 FIT groups per fold, fixed6 variants,
FIT noise1701/1702; source labels only from own FIT groups. Pretraining batches
use seed+1000 independently restarted for each coordinate: identical rows and
full/low flags. Adaptation uses the original shared group_schedule seed+9000,
300 grouped64 batches, identical across three paths. No new renderer recipe/data.
Original A objective plus ordinary aligned anchor .2, learning rate .003, unchanged
all_terms four branches/groupA+groupN auxiliary work in every adaptation arm.
Original FIT-only temperature calibration, coupled serving and five gates unchanged.
The training/serving law mismatch is not repaired. No rowN arm is introduced.

## Initialization, shared decoder, and conversion
For each cell initialize ONE exact raw Source model and train its decoder300 steps.
Copy that same raw initialization/learned decoder into matched raw and Haar models;
Haar input is xH and encoder is H^T W, NOT the same numerical W under different
inputs. All other parameters are copied identically. Per-parameter Adam clocks
make discarded decoder moments irrelevant to content training: raw500CE is required
to reproduce the old raw base digest exactly. Four decoder fits are charged once,
not eight: 4 temporary decoder owners +8 content-base constructions are disclosed.
Both content bases then perform500 CE steps and retain the same decoder tensors.
Actual decoded text/image semantics must equal canonical0..11; no relabeling rescue.

At adaptation create fresh clones using explicit timing mode and exactly one of
(raw,raw),(raw,haar),(haar,haar). All three clones calculate encoder_coordinates
once: same-coordinate paths discard it, raw→Haar selects it. All moments and update
counters reset; no transport of old Adam moments. Every matched input masks commands,
calculates Haar features once, raw discards and Haar selects. This is matched work,
not natural deployment timing. Qualified helpers/default Source remain byte-exact.
New helper admits exact MatchedHaarModel only; invalid mode/path/source or nonfinite
parameters reject. Existing representation digest law remains unchanged; new timing
mode/path are explicitly recorded in model metadata. Checkpoints remain disabled.

Entire fixed FIT full/low initial-function and adaptation-boundary hidden/text/image
outputs must be within fixed1e-12 absolute error, and nonencoder tensors exact.
This is the already selected engineering admission, not a universal IEEE theorem.
No model observations selected it here; old qualified toy3e-15 and normalized
serving guards remain unchanged. Any guard failure stops the entire once-run.
Initial boundary: shared raw reference +2 content models ×2channels×4cells=24
forwards. Adapt boundary: raw reference+RR+RH, Haar reference+HH, ×2×4=40.
Total64 boundary forwards/49920 rows, fully charged. No postfailure tolerance repair.

## Controls, freeze barriers, outcomes
Four historical raw base digests/full metrics and eight RR/RH adapted digests/full
uncalibrated+calibrated metrics/FIT records/profile keys/datasets must exactly match
the completed Haar-A study. No weights restored. HH has no historical target.
All12 adapted weights, then all24 calibrated heads freeze before known heldout
noise3701/3702/3711/3712 is regenerated. Original TEST/VAL closed. These catalog
groups/noises are previously studied, not fresh global holdout evidence.

Primary HH−RR and HH−RH each have8 unpooled original five-gate comparisons:
CE gain>=.005; text mass, greedy text, joint success no decrease beyond1e-10;
pixel MSE no increase beyond1e-10. Overall is the conjunction of all16 passes.
RH−RR is an unchanged descriptive control. All3 self-calibration claims retained;
6claims×4cells×(2noise+pooled)=72 full contrasts, all11 metrics/full-low-macro/
all-partial. All8 base full metrics retained. No pooled/subgroup/old-history rescue,
seed selection or threshold tuning. Only a future separately authorized study may
consider N after both strong A controls pass; this experiment cannot claim NDU gain.

## Prospective work and costs
30CPU/90wall/512MiB/4MiB, CPU0 single thread, original synthetic shared lock,
nonblocking refusal, complete wait4, no retry/extension. All50 literal tests run
before FIT generation: old47 byte-exact plus3 new timing tests (initial function/
shared decoder and raw CE parity; three-path clone/reset/A-anchor update parity;
refusals/checkpoint). Toy initializations/Adam updates counted; old4 manualSGD
parameter steps additionally reported. No separate hidden qualification run.

8 content bases,4 shared decoder owners,12 adapted clones;1200 decoder,4000
supervised,3600 adaptation updates.18928 forwards/1334240 rows;1212 decode calls/
14544 images.24 calibrated heads×28=672 NLL evaluations/1048320 head-row evals.
64 evaluation serving calls/99840 joint tables, all normalization/support/CDF/SHA
work retained. Exact ledger in LEDGER.1200 schedule batches reused across3 paths.

Per-coordinate global work is not equal because the raw base serves TWO paths:
raw8 encoder transforms/256 column rows,8848 input transforms/613120 rows;
Haar12 encoder transforms/384 column rows,10072 input transforms/714880 rows.
Within every corresponding input/conversion call both coordinates calculate the
same transform, selecting/discarding only; shared raw pretraining is not duplicated
or charged twice. Base/clone phase counters, shared decoder cost, conversions,
boundary scans, pretraining/adaptation/FIT/serving CPU, whole child and SHA costs
are explicit. Eight source initializations refers to content bases, not all
constructor calls (the4 decoder owners and12 clones are separate).
Each standalone path has logical500CE+300A (and the same300decoder preparation).
Unique raw pretraining is shared by RR/RH, while HH has its own500CE preparation.
The candidate is NOT claimed CPU-budget identical to an amortized control: report
each unique-base preparation and each adaptation separately, along with the4
shared decoder fits. Never add shared raw preparation twice to the whole-study
actual cost. Equal logical update budgets do not imply equal CPU or wall time. Preparation, reviews,
prior qualifications and historical studies are additional, unknown costs notzero.

Producer writes source/AST/hash only; no scientific imports, execution, payload,
lock or remote operations. Independent review and parent once-run admission required.
