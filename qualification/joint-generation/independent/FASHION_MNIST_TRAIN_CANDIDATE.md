# Fashion-MNIST: bounded TRAIN candidate, not a result

Disposition on 2026-10-23: **worth one bounded development probe after source
implementation and review**. A noisy product thumbnail leaves its clean instance
pixels and category unresolved. There is no supplied scene description that a
renderer can directly realize. This removes the specific CLEVR adaptation defect;
it does not establish any advantage for dynamic computation. Ten category words
are a narrow classification interface, not open language generation.

This commit contains a proposed task and an integer-only operation inventory.
No Fashion dataset, sample, model, training, timing benchmark or evaluation was
executed. `plan.json` is a review candidate, not a runnable/frozen experiment.
Existing r1 limitations, r2 failures/unopened test, CORE c1 failure/sealed test,
H2/H3 startup failures, D1 cost failure and H4 negative diagnostic remain intact.
It neither repairs nor passes any old qualification gate. The separate content
and NDU research branches are not reimplemented here.

## Official source and narrow applicability

The [pinned official README](https://github.com/zalandoresearch/fashion-mnist/blob/b2617bb6d3ffa2e429640350f613e3291e10b141/README.md)
describes 60,000 TRAIN and 10,000 TEST 28×28 grayscale images and ten labels.
The [official paper v2](https://arxiv.org/pdf/1708.07747v2), section 2, describes
front thumbnails of 70,000 unique products and 6,000 randomly selected TRAIN
images per class. This is the authors' provenance statement. The
[reader](https://github.com/zalandoresearch/fashion-mnist/blob/b2617bb6d3ffa2e429640350f613e3291e10b141/utils/mnist_reader.py)
returns only uint8 image rows and labels; it supplies no SKU identity mapping.
We can independently group identical published pixels, not verify physical
product independence. Published pixels are processed reference thumbnails,
not original unprocessed photography; no official segmentation mask is supplied.

The [official project license](https://github.com/zalandoresearch/fashion-mnist/blob/b2617bb6d3ffa2e429640350f613e3291e10b141/LICENSE)
is MIT, copyright 2017 Zalando SE; its notices must accompany copied material.
This does not license unrelated catalog photography. Three official source text
files, 24,576 bytes, were inspected and hashed. The publisher's approximate
compressed sizes are 26 MB TRAIN images plus 29 KB labels, and 4.3 MB TEST images
plus 5.1 KB labels. Derived uncompressed IDX sizes are 47,100,024 bytes TRAIN and
7,850,024 bytes TEST; data bytes/checksums were **not** independently verified.
The source manifest records publisher MD5 values, not observed data hashes.

One read of the official `data/fashion` directory was denied as a restricted URL;
the exact error is retained in `scope-and-access.json`. It was not retried or
bypassed. It does not establish whether a future authorized data-file read would
succeed. No such read was attempted in this candidate review.

## Fixed task, distribution and information boundary

Use all ten classes and all 60,000 original TRAIN rows at their original weights.
Let x be the published uint8 reference divided by 255. Fix one noisy input per
source: z = clip(x + 0.20 epsilon, 0, 1), epsilon standard Gaussian. This sigma is
chosen before inspecting data or action gains. It is not class dependent, route
dependent or selected for oracle headroom. No crops or new data augmentation.

Future intake must verify publisher hashes and IDX headers, record SHA256, and
group exact pixel duplicates by SHA256 of the 784 uint8 bytes. Group assignment
is the integer SHA256(`hepta-fashion-split-v1\0` || pixel_hash_bytes) modulo 6:
0–3 FIT, 4 SELECT, 5 SCREEN. Duplicate multiplicity is retained; all copies stay
together. Report conflicting labels without deleting or repairing them. These
are approximately 40k/10k/10k rows; actual sizes and per-class counts must be
published before fitting. An absent class stops intake; do not choose a new salt.

Noise uses PCG64DXSM in NumPy 2.3.5, seeded with the first 128 bits, big endian,
of SHA256(`hepta-fashion-noise-v1\0` || pixel_hash_bytes). Generate float64
standard normals, add in float64, clip and cast once to float32. All methods
receive these same bytes. Service sees only z and the public fixed sigma. It
does not receive the clean reference, true class, row/group ID, actual epsilon,
noise seed, residual target or an observer using any of them. All splits and
noise choices are independent of model scores. Official TEST remains unread.

Only FIT updates content/critic parameters. SELECT chooses a fixed schedule or
one checkpoint once per declared stage. SCREEN is consumed once after all
choices are fixed, as a development screen, never a confirmation study. No
SCREEN-driven repair, threshold search or rerun. Any later confirmation needs
its own prospective protocol, complete prior-study history and cross-study
error control; earlier 95% intervals cannot retroactively share a new alpha.

## Actual content state and three legal actions

Use the small shared model below, with tanh hidden activations, a softmax text
head and a continuous residual pixel head. Split z into 49 nonoverlapping 4×4
patches; positions are fixed two-dimensional coordinates. Shared weights across
steps keep the candidate small.

| Module | Input → output | Parameters |
|---|---|---:|
| Global c | z784 → 64 | 50,240 |
| Text state T | c64 → 32 | 2,080 |
| Image state I, shared across patches | [c64,z_patch16,pos2] → 16 | 1,328 |
| Text decoder | T32 → 10 probabilities | 330 |
| Pixel decoder, shared | I16 → 16 residuals, add z_patch and clip | 272 |
| qT | [T32,p10] → 16 | 688 |
| qI, shared | [I16,mu16,z16] → 16 | 784 |
| Feedback f | [c64,qT16,mean(qI)16] → 32 | 3,104 |
| T residual update | [T32,c64,f32,qT16] → 32 | 4,640 |
| I residual update, shared | [I16,c64,f32,qI16,pos2] → 16 | 2,096 |

Content parameters total 65,562. T updates the actual category posterior; I
updates 784 instance pixels. J performs both updates in parallel from the same
old state. Changed heads are decoded once; unchanged heads and modality
observations are cached in **every** implementation. Feedback through p and mu
is differentiable, with no detach hidden in an alleged full gradient.

The minimal policy always performs J first, then chooses only the last action
T/I/J from the new legal f32. A 32→8→3 value network has 291 parameters and
280 forward MAC; the constant remaining-step feature is folded into its bias.
Two drafts are computations of the same input, not new external observations.
The plausible opportunity is conditional error type: some examples may benefit
more from changing category belief, others from spatial residual correction.
T does not directly improve pixels and I does not directly improve text in the
last step, so action crossing and predictable value must actually be observed.
No crossing, little predictable value, or uniformly dominant J are legitimate
negative outcomes. The prior finite12 H4 bound is not transferable to this task.

## Loss, sampling law and scoring

All routing comparisons use the **same** content objective and supervision
weights. Fix Adam, LR 0.001, B64, seeds 11/23/47; cycle the nine two-step
sequences in hash-seeded batches independently of labels or their gains. A
four-epoch workload is the planning reference, not an excuse to exceed the cap
or prevent static methods from spending savings on further useful training.
The initial checkpoint is after two epochs or the first 150 content CPU seconds
per seed, whichever boundary is reached first. Initial SELECT chooses S's
constant schedule. D then continues the uniform nine-path cycle; S continues
that chosen schedule. Direct/deep/CNN continue their single content graph.
Content continues to its declared subcap, not merely four epochs. Freeze the
final content weights before generating any policy labels: the single OOF and
full policy fits use these final weights, and content cannot change afterward.
D uses this final checkpoint. Static selection may retain its better initial
or final checkpoint/schedule, with all evaluations charged. No intermediate
checkpoint search or policy refits after looking at SELECT or SCREEN.

Let p_y denote the true-category probability only inside the offline loss.
The common anchor is CE(p,y) + MSE(mu,x)/0.04. For an explicit auxiliary output
law, use K=4 terminal samples v_k = clip(mu + 0.05 epsilon_k,0,1) and
q_k = exp(-MSE(v_k,x)/0.04). K repeats terminal sampling/loss, **not the backbone**.
Exactly marginalize the ten categorical outcomes:

    A = p_y mean(q_k)
    Z = 1 - p_y + p_y mean(exp(-2 q_k))
    N = -log(Z)/2
    content loss = common anchor - 0.1 N

rho=2 and both weights are fixed. With finite K this is a fixed-K auxiliary
risk objective; its log-ratio gradient is not an unbiased population entropic
gradient. This candidate isolates routing under a common NDU objective; it
does not independently establish NDU's contribution over additive training.
Any such additional claim requires a separately matched A-versus-N comparison.
Never teacher-force the true class into the image branch.

Primary service returns the argmax category's canonical UTF-8 name and the
**actual float32 mean-image pixels** mu. Clip then serialize; score the decoded
transport bytes, not an untransmitted tensor. Stochastic auxiliary risk is
reported separately from this greedy/mean service. Fix E = MSE(output,x),
A_word = actual word correctness and U = A_word exp(-E/0.04). Also publish
unconditional accuracy, MSE, per-image PSNR and PSNR from overall MSE, all per
class and source. Preserve infinite PSNR for zero error. Joint U alone cannot
prove that both components improved; component regressions stay visible.

Pixel controls return noisy z, black, or the FIT mean image of the **predicted**
category, always with a legal noisy-input classifier. The true class is never
used to select service pixels. Offline, compare the correct output/reference
pairing with a fixed within-class permutation of the same outputs. Report
target-pixel support x>0.1 and background errors on all rows; this is a scoring
definition, not an official mask. Do not filter to correctly classified rows.

The existing generic image contract is float32 RGB. A future backend adapter
should replicate the gray plane to RGB, require identical channels and score
one plane; 3,136 gray bytes become 9,408 transport bytes per output. Keep the
existing text/image/audio/video contracts and explicit capabilities. No Fashion
adapter exists in this commit, and the old rgb8/finite-code backend cannot serve
this task. PNG previews, if generated, are charged and never replace float
scoring. The former twelve-code PNG cache does not apply to continuous images.

## Smallest informative TRAIN study and fair static alternatives

1. Implement/load/export and derivative checks on synthetic hand-made tensors,
   including T-only/I-only/J output changes, no input-label channel, and loss
   gradients through both feedback branches. Freeze the runner before intake.
2. Train the three-seed content candidate within the proposed complete budget.
   Select 512 FIT groups by smallest independent hash, retaining their original
   row weights; require all classes without resampling. Evaluate every fixed
   depth 0/1/2 sequence with common-prefix reuse. Compute actual greedy raw
   utility oracle headroom of the three J-prefix final actions against the best
   constant depth 0/1/2 sequence, action frequencies, per-class/source crossings,
   and measured complete path costs. This oracle is a quality bound only.
3. For the J prefix, fit one last-action value regressor. Use three group-hash
   OOF folds on those 512 FIT groups, 256 Adam updates/B64 per fold, then the
   same 256-update full FIT-label fit. Train against the three actual terminal
   U values; choose argmax with fixed T,I,J tie order. No gain threshold search.
   Report OOF regret to oracle and to the best constant action, including
   wrong-action tails. Labels use references only offline. The policy can
   change conditional compute; it cannot obtain the reference at service.
4. Stop this candidate if any seed has no positive raw oracle headroom, or OOF
   policy raw U does not improve on its best constant action in every seed.
   This conservative screen is a research continuation rule, not a statistical
   success test. A positive result still needs the strong complete-budget
   comparisons below; no median-mixture proxy is a strict CPU upper bound.

Required static families are optimized direct classifier+denoiser MLP
(101,850 parameters/100,992 forward MAC), deeper MLP
784→320→192→128→(10,784) (439,962/438,528), same-resolution 3×3 CNN
1→4→8 with a 1×1 image head 8→1 and flattened category head (63,075/323,008), and all
fixed 0/1/2-step schedules of the shared backbone. Search all nine depth-two
sequences, not merely JJ, and continue useful content training for the selected
fixed schedule with policy savings. SELECT checks occur only at the common
initial checkpoint and the one final checkpoint; both costs are charged.
All direct/deep/CNN image heads also output a residual added to z before
clipping, with the same objective and supervision weights as D.

Also require exact compiled feedback: compute the final T and I candidates
once and select/compose their heads with the same policy, reproducing D's
output law without per-row update dispatch. It retains input dependence, but
has a fixed execution graph and is a legitimate competitor. Do not reject it
by relabeling it dynamic. A distilled direct MLP uses FIT teacher p/mu targets,
the same LR/B64 and remaining content quota. Teacher construction/labels,
student fitting and selection are charged. If compiled or distilled feedback
wins, acknowledge that implementation
instead of claiming a unique dynamic advantage. Both compiled and distilled
candidates are required in this family, not alternatives that can be omitted.
Use KL(teacher p || student p) plus MSE(student mu,teacher mu), each weight 1,
**added** to the common supervised objective. Evaluate both final candidates;
charge the common teacher construction once to this family and record the
full standalone bill for each exported descendant. Exact compilation receives
an output-parity check; distillation is approximate and receives no exactness
claim. No SCREEN result selects or refits the student.

Propose a new limit of **1,800 process-plus-descendant CPU seconds per complete
three-seed arm**, 2 GiB peak RSS and 2 GiB retained payload. This is not the old
10-second/12B qualification and makes no old passing claim. Six complete arms
are D, fixed-schedule family, direct MLP, deep MLP, CNN, and compiled/distilled
feedback family: at most 10,800 physical CPU seconds if all are needed. The
initial headroom probe is part of D's bill and of every arm reusing it, never a
free preliminary experiment. Stop before other arms if the probe is negative.

Proposed arm scheduling: 150 CPU seconds shared intake/preparation, 450 CPU
seconds build per seed, then 300 CPU seconds for complete SCREEN service and
reporting: one pass per seed for ordinary arms, both candidates per seed for
the compiled/distilled family, plus the declared output controls. In each seed,
D permits up to 300 seconds content
updates and 150 seconds policy/selection/export. Static methods permit up to
425 seconds useful content updates and 25 seconds selection/export; the
compiled/distilled arm uses the full 450-second per-seed build allowance for
its charged teacher plus remaining compilation/distillation, without imposing
the ordinary static 25-second selection split on its teacher. These are
subcaps, not mandatory expenditures or padded
work. Train in deterministic batches until the next-step reservation would
exceed the relevant subcap; reserve estimates must be fixed by a single bounded
FIT-side calibration, charged to the arm. Inability to complete a required
phase terminates that arm; retain partial outputs and nonzero status. Do not
repeat for a faster timing draw. No unimplemented reservation rule is claimed
verified here: its exact code and zero-data boundary tests remain a pre-run gap.

Complete CPU includes loading/decompression/checksums, grouping, noise/RNG,
gradient/loss/optimizer work, all search and critic labels, OOF fits, compiler
processes, teacher/student construction, validation, export/reload, actual
service dispatch, float/JSON and optional PNG output. Shared physical work is
charged in full to every standalone method that needs it. Independent methods
do not inherit a teacher's outputs for free. Record both actual spending and
cap; unused allowance is unused, not imaginary compute. All methods receive
the same applicable caching, fusion, precision and batch optimizations.

SCREEN evaluates each original row once per seed, B64 with the final partial
batch retained. Under the common complete cap, require D's mean U to exceed
the strongest completed static family **in each seed**, with accuracy no lower
and MSE no higher in each seed, before proposing confirmation. Report all
component differences and actual total CPU, service latency, memory, updates
and parameter distances. A missing required strong baseline means this research
screen is incomplete. D's paired MSE must also be strictly below noisy identity,
black, predicted-category mean and its fixed within-class-permuted outputs in
every seed; otherwise the candidate has not shown useful instance restoration.
These controls reuse the same legal classifier and retain their full costs.
No significance or scientific success is declared from
this development rule; no new economic price or horizon is invented to rescue
a quality deficit. Later confirmation must predeclare its lifecycle horizon
and cost price, or a cost-quality frontier, before any new test is opened.

## Feasibility boundary and next implementation work

The integer calculator gives 129,376 initial forward MAC and
336,448/445,984/450,912 for JT/JI/JJ. JJ forward+backward is 1,260,224 MAC.
Three J-prefix final actions cost one shared 450,912-MAC expansion; all nine
sequences cost 695,840, not nine separate calls. Four epochs over approximately
40k FIT rows and three seeds require about 474.414 billion uniform-path MAC,
before loss, RNG, optimizer or selection. Even assigning the whole 1,800 seconds
to this content work requires about 0.264 GMAC/CPU-s. Real throughput is unknown;
the actual D content subbudget is 900 seconds across seeds, requiring about
0.527 GMAC/CPU-s for that reference workload before other content costs. No
speedup or completion is promised. Smaller action MAC is not measured CPU.

FP64 weights, gradients and Adam m/v for content+policy occupy 2,107,296 bytes.
`model-inventory.json` explicitly counts a JJ tape/K4 buffer inventory, all
affine concatenation inputs and a same-sized backward reservation; it is not a
peak-RSS proof. uint8 TRAIN pixels occupy 47,040,000 bytes; float32
materialization would be 188,160,000. Python,
BLAS workspaces, gradient implementation, optimizer temporaries and dataset
metadata need actual RSS accounting. Torch is absent; the proposed NumPy path
needs real vector-Jacobian implementation/parity tests before fitting.

This is a useful restoration/control test only if instance fidelity exceeds
the noisy/prototype controls and legitimate feedback predicts action value.
It may favor an efficient static CNN or compiled graph. If the fixed probe
fails, retain that boundary rather than alter sigma, select classes, inject
route-specific damage or expand the critic until positive. No richer-dataset
search, new training or new official evaluation is authorized by this document.
