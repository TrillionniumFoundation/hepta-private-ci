# Fixed original-FIT group-held-out replication v1

## Question and scope
Does the already fixed post-transport positive-temperature calibration retain its
own-model quality gains on scene/instruction groups absent from that new model's
training and calibration? Does fairly calibrated NDU beat fairly calibrated
additive training by the unchanged substantive gate?

This is a prospective finite RGB experiment, not an original-TEST evaluation,
not a claim of globally never-observed groups, and not evidence for arbitrary
natural-image generalization. The 260 original FIT groups have historical exposure
to earlier models and informed this research direction. Known twelve scene/class
templates remain shared task vocabulary, including decoder supervision for all
classes: this is instruction/scene-combination holdout, not unseen-class or
unseen-template learning. Original validation and TEST observations are unused.
The legacy catalog function constructs split membership metadata, but no original
validation or TEST observation is rendered or evaluated.

## Fixed allocation and model independence
Use the existing original FIT catalog order unchanged (legacy seed 771), without
looking at outcomes. Fold f holds out catalog[f::2], training on catalog[1-f::2].
Both sets contain 130 groups. Each group has six corruption variants, 780 rows.
No split search or stratification retry. Abort if a training fold lacks any of the
12 labels, or a heldout partial-command population is empty.

Seeds 71 and 89 are fixed in both folds. Four bases are independently initialized;
no weights, optimizer moments or fitted temperatures cross folds. Opposite-fold
training groups equal this fold's heldout groups, as ordinary cross-fitting, but
there is no model selection or ensemble based on results. Reused random seed
numbers couple initialization schedules, not learned state. All eight adapted
models and their sixteen fitted head temperatures freeze before generating any
fresh heldout-noise observations or metrics. Fitting uses only that model's
training fold. No outcome-dependent model/seed/fold selection or fallback.

FIT noise seeds: fold 0 = 1701, fold 1 = 1702. Heldout noise seeds: fold 0 =
2701/2702, fold 1 = 2711/2712. Two heldout corruptions share groups/labels and must
have disjoint exact input hashes. The data renderer, corruption range, instruction
encoding and full/low conversion are unchanged. This changes training diversity
from 260 to 130 groups while retaining updates, increasing reuse per sample;
comparison to old 260-group scores is not a causal generalization estimate.

## Equal treatment and fixed algorithm
Each base: decoder 300 updates at .05; supervised 500 updates at .003, batch 64,
50/50 full/low. Each additive/NDU clone: reset optimizer, 300 updates at .003,
batch 64, same batch indices and channels within base; anchor .2 and rho 1.5.
Both arms compute the same four raw/aligned A/N terms and both anchors, selecting
the respective aligned objective. Readonly base forwards remain charged.
No optimizer change, unbiased-Adam claim or sample-budget equivalence claim.

Use unchanged qualified normalized coupling and temperature helper bytes.
Temperature fitting uses both channels of the model's own 780 training rows:
1560 rows/head, marginal NLL, inverse temperature in [1/8,8], 24 bisection steps,
28 evaluations/head including identity/endpoints/selected result. Both strong
additive baseline and NDU receive the same calibration. Actual served CDF law,
argmax, support and model/profile binding checks are unchanged. No VAL tuning.

## Evaluation and predeclared decisions
After the global freeze barrier, evaluate every base and all eight adapted models
on their own fold's two fresh heldout views, full/low and their macro average.
For each adapted model evaluate uncalibrated and calibrated service on cached
identical raw marginals. Report all and partial-command populations, all original
metrics, both noises and pooled descriptive values.

Original five gates on full/low macro partial commands are unchanged:
- certainty-equivalent reward gain >= .005;
- text probability mass, greedy text accuracy and joint success each >= -1e-10;
- pixel MSE delta <= 1e-10.

Self-calibration success requires all 16 unpooled fold/seed/objective/noise
contrasts pass. Fair NDU increment requires all eight unpooled fold/seed/noise
N-calibrated minus A-calibrated contrasts pass. Overall is their conjunction.
Pooled values cannot rescue a failed component. Uncalibrated N minus A is retained
as control. No significance or independence claim: folds and noise views share
finite catalog structure. Retain failures; no resplit, retry or parameter sweep.

## Prospective exact work inventory (not measured costs)
4 new bases, 0 model payload restores, 8 clones; 1200 decoder + 2000 supervised +
2400 adaptation updates. Forward batches = 4000 + 7200 + 16 + 24 = 11240.
Forward rows = 256000 + 460800 + 12480 + 37440 = 766720.
Decode calls = 4*(300+1+1) = 1208, decoded images 14496.
Two FIT-fold dataset calls, four heldout-noise calls, zero TEST dataset calls.
Adaptation all-terms calls 2400; four-profile utility rows 614400.
FIT base serving calls 8/tables 12480; fitted heads 16/head-rows 24960;
NLL evaluations 448/head-row evaluations 698880.
Evaluation serving calls 40/tables 62400/entries 8985600;
CDF marginal checks 124800; calibrated internal base tables 24960;
calibrated argmax and support row checks 49920 each.
Base-profile roundtrips 12 and calibrated-profile roundtrips 8.
Runtime rejects any inventory mismatch. 21 literal prerequisite tests run before
model preparation; their cost is inside the same child's receipt, not free.

## Admission and terminal accounting
SOURCE ONLY: no run admitted by this document. Independent static review and
parent admission are required before executing the supplied single-use supervisor.
Proposed cap: 30 CPU seconds, 120 wall seconds, 512 MiB, 4 MiB per output,
CPU 0 / numerical threads 1. Supervisor uses the existing synthetic-only shared
lock, nonblocking refusal, no creation of a substitute lock, no automatic retry,
full wait4 including killed child, and records actual child CPU/wall/RSS/exit.
No original task lock replacement. No model payload reads/writes. Only new bounded
run JSON and stdout/stderr; source and historical qualification metadata frozen.
Base preparation, all training, calibration, tests, data generation and evaluation
are included. Source preparation/review, supervisor tail and historical research
are separately disclosed, not silently assigned zero. Runtime measurements—not
this arithmetic ledger—determine actual costs.
