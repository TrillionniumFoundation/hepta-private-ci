# Independent questions and reproducible Encoder-study evidence

Continuation of #1550 from `9b4f262ddaf19bd78604aa7018e74797496a7557`.
The original `cases` generator and all analytic/finite-tree study implementations
are retained. There is still one study runner and no new scientific acceptance
service or production authority. This extension is NOT a nonlinear/general FBSDE.

## Why the question generator matters

The original generator chooses the true intent as target with probability 1/2;
otherwise it chooses one of three incorrect intents uniformly. If q_j denotes
P(class=j | text) before that question is generated, then Bayes' rule gives

    P(class=j | text, target=j) = (q_j/2)/(q_j/2+(1-q_j)/6)
                               = 3*q_j/(1+2*q_j).

Thus raw pre-question semantic probabilities are not generally the conditional
belief law used by the label-balanced task generator. A perfectly uninformative
q_j=1/4 becomes 1/2 after conditioning on the generated target. This does not prove
how much an actual trained model is wrong: its q_j may also be miscalibrated.
It identifies a model/design mismatch before interpreting any arm's superiority.
Historical predictions are not silently recalibrated or relabelled.

`independent_targets_v2` constructs the public question from an ID-only inventory.
Each target is sampled uniformly without reading any intent label. Label reading
is a separate scorer/fit operation. Permuting labels cannot change the generated
questions. Source order is canonicalized, so label-sorted row ordering cannot be
used as another generator input. The underlying publisher partitions remain the
same stratified sample; this is not a newly independent future dataset.

V1 remains `label_balanced_v1`, the default for command compatibility. The physical
workflow runs both profiles in separate jobs with unique artifact names; the V2
job adds a cheap `syntax_prior` control with Bernoulli 1/4 leaves. It does not call
the semantic Head, and its standalone lower-bound accounting excludes unused
semantic training and Encoder work. Both profiles retain all original eight
controls, including the algebraically equivalent f=0 tree/exact comparator.
All learned and solver arms still receive identical available information.

## Interpretation must survive the cheap controls

Generated four-leaf questions have very different class prevalence by formula.
For example the V2 all-AND syntax prior is 1/256, not 1/2. Therefore outputs include
formula-stratified positive/negative counts, per-class recall and balanced accuracy.
A stratum with no positives or no negatives has undefined balanced accuracy, not
a perfect score. Overall accuracy alone does not establish reasoning.

The source census computes transitive connected components by original text
hash. Reusing an utterance across multiple cases does not create independent
observations. The current report provides no IID case confidence intervals and
does not authenticate independence even when components are disjoint.

## Replay and measured cost

Both runs preserve original public case inputs, semantic leaf probabilities,
all predictions sealed before test scoring, original test labels, and current
source identities. Physical runs additionally preserve bounded public-data raw
and normalized vectors and the training-only normalizer in `frozen-features.pt`,
with its original byte hash. No pretrained weight bytes are uploaded. These
vectors permit later CPU replay; their hashes are not independent execution proof.

`fbsde_audit.recompute_comparison` imports neither solver nor learned model. It
recomputes labels, rendered sentences, accuracy/Brier, full-world probability
sums, paired inventories, source components, and physical preparation/inference
CPU sums from original files. It is an arithmetic audit, not a PASS report that
can grant model promotion. Fake totals, changed text and label drift are tested.

The study records a measured CPU envelope, disjoint classified jobs and explicit
unattributed preparation/reporting work. Per-arm adaptation/inference and physical
standalone totals are labelled LOWER BOUNDS, because initialization, common
recording, evaluator work and attribution are not fully allocated per arm. Common
budget ceilings still do not mean equal actual resource consumption. Preparation
and validation/calibration selection are not amortized over hypothetical use.
The outer CPU envelope ends before final report/audit output; it is not energy or
an end-to-end native request measurement. Migration is unexecuted, not qualified.

## Executed checks and remaining work

Local final qualification subtree: 208 model-free tests plus 21 real Torch tests,
no skips. New tests exercise ID-only generation, label/order invariance, exact
Bayes correction, transitive source grouping, undefined stratum metrics, complete
V2 fit/selection/inference/decoding and arithmetic audit rejection. Old and updated
V1 runners executed the same explicit fixture vectors and produced identical
probabilities, text, depth and solver records on all 8 x 192 cases (maximum
probability difference 0). This is compatibility evidence, not pretrained efficacy.

Real mmBERT results require fresh exact-source hosted execution for each profile.
No queued job, random fixture vector, changed label model or small BSDE residual
is a real Encoder advantage. Native ownership, no-change, future observations,
retention, risk and full lifecycle gates remain unchanged. Keep the PR Draft.
