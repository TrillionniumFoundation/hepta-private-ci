# Native joint content distribution: feasibility analysis, not a training result

This is the next source/table-only analysis on the isolated content branch.
There is no model training, model forward, decoder forward, sampling, rendering,
threshold search, timing experiment or formal data opening. The accompanying
calculator reads existing TRAIN receipts and decoder-observation tables only.
The proposed training protocol is a new draft; it does not amend a consumed plan.

## Evidence and its limits

The parent independently reviewed result `e7de57f667c56dffd1f1caf5bed742efb89aba77`:
fixed-model TRAIN decoding readiness, original freeze, supplemental capture
identity, four caps, complete joint Q/requestwise CE and greedy contract held.
Its negative tradeoffs and smaller A−H were also confirmed. The twelve actual
two-stage service records contain **384 primary log2 requests and zero primary
repairs**; only secondary A23/row42 repaired once. Per-profile setup/return was
not separately timed. The old `complete_CPU_net_CE` field is not complete service
net benefit. No repeat timing or sampling is performed here.

Reconciliation's larger H gain and the A−H CE gap shrinking from .00510121 to
.00101608 motivate a native joint static baseline. They do not prove training
benefit, a representation bottleneck or NDU improvement. Prior refiner and fixed
1:1 alternation failures remain failures. No rejected gate or anchor is resumed.

Relevant executable sources are `model.py`, `data.py`, `independent/data_v2.py`,
`independent/learning.py`, `independent/accounting.py`, `independent/native_adam.py`,
`independent/native.c`, `independent/evaluation.py` and `utility.py`. The analysis
JSON binds these, actual TRAIN R tables, baseline weights and receipts by SHA256.
No paper is needed to infer these finite-model equations.

## What the current task actually permits

`independent/data_v2.py` constructs one transformed scene target y per request;
both generated modalities are required to describe it. The text output vocabulary
is twelve parsed captions. The original learned RGB decoder maps twelve codes
to twelve fixed 8×8 RGB images. It has no input-dependent pixel residual or
continuous image latent. Both proposed heads retain those exact decoder weights.

The three saved original observation tables give text_sem(c)=image_sem(c)=c for
all twelve codes. This is an observation of learned pixels through template MSE,
not an assumption based on code names. Correct-code MSE is approximately
3.60e−5 to 4.85e−5; the smallest nearest/second-nearest template margin exceeds
.01981. Existing output code rounds pixels to uint8. For binary templates, this
can change a pairwise MSE difference by at most 1/255≈.003922, so the observed
margin certifies the same nearest semantic class after PNG quantization without
rendering another image. Existing PNG audit evidence is also retained.

Thus a semantic latent c producing caption(c) and original learned image(c) is
legal for **these fixed decoders and this same-semantic task**. It can still pick
the wrong c; it cannot repair pixel fidelity or create another image. A future
decoder with a missing/duplicate/permuted semantic class would invalidate this
particular identity mapping. Future execution must check actual decoded maps
again, reject a mismatch and preserve it; no silent code remapping or critic fit.

There is a stronger scoring-specific fact. For every off-diagonal pair (t,i),
KEEP the image i and replace the caption by caption(i). With the observed maps,
the unchanged reward difference is .05 when y=t, .95 when y=i and .35 otherwise.
The pixel term is identical. The calculator checks all 12×132=1,584 entries per
seed directly against saved R. Therefore this task's reward admits an agreeing
output that pointwise dominates every disagreeing output, for every target.
Both expected reward and fixed positive-rho entropic utility are monotone under
that transformation. Diagonal support does not remove a reward-optimal output
for these decoders. This is a consequence of the current .35 contradiction versus
.3 single-modality reward, not a general multimodal theorem. Text-only factual
correctness can still be lost when agreement follows a wrong image.

## Three conditional distribution families

Use the same input dimension202, tanh encoder width32 and fixed decoder.

| Family | Per-request law | Distribution degrees of freedom | Active content parameters |
|---|---|---:|---:|
| Existing two12-way heads | Q(t,i)=p(t)q(i) | 22, rank-one independent law | 7,288 |
| Shared12-way semantic latent | Q(c,c)=s(c), all other cells zero | 11 | 6,892 |
| General144-way head | Q(t,i)=softmax(z)[12t+i] | 143 | 11,248 |

The degrees of freedom describe one law, not arbitrary input functions: logits
are linear in the same32-dimensional h. Independent and diagonal families are
different restrictions. A non-degenerate diagonal law is correlated and cannot
be replaced by s⊗s. General144 supports both in its closure; an ordinary finite
softmax has positive off-diagonal entries, so exact zeros require a mask or a
limit. No mask search or additional variant is proposed.

General144 can express asymmetric uncertainty, correlated errors and arbitrary
pairing, which matter for other task contracts. Here it spends additional
parameters, gradients and categorical normalization on outcomes dominated by
agreement under the frozen scorer. This does not prove a smaller head optimizes
better: hidden-feature capacity, finite training, conditioning and implicit
regularization remain empirical issues. The larger head may represent different
input functions even when its useful output support concentrates near diagonal.

Neither family changes the twelve actual image outputs or the caption vocabulary.
Shared12 removes mismatching combinations; general144 retains all144 pairs.
The choice is about their conditional law, not an expanded image generator.

## Minimal candidate: one native12 head

Choose shared12 for the next **draft**, and do not train144 as a parallel candidate.
For each common pre-adaptation base seed, copy its encoder and decoder. Initialize
W_shared=W_text+W_image and b_shared=b_text+b_image. Then

    s(c) = p_base(c) q_base(c) / sum_j p_base(j) q_base(j).

This is exactly the old law conditioned on equal codes, implemented by a single
linear head; it is not the previous threshold reconciliation law. Save a zero-
update observation and distinguish this coupling/conditioning gain from later
parameter-training gains. There is no initialization temperature or blend sweep.
For comparison only, a general144 head could initialize each column as
W(t,i)=W_text(t)+W_image(i), b(t,i)=b_text(t)+b_image(i), exactly recovering p⊗q.

Every native request draws one c from s, emits the original caption and renders
the original learned image once. Native greedy is argmax(s), with first-index
ties. This is a newly declared contract; it does not relabel the old separate-head
greedy results. There is no second repair, image observer, dynamic routing or
early exit. All active encoder/head groups receive real gradients each update.

## Preserve the anchor and the original joint utility

For **every** distribution family, use the original average modality CE:

    C(Q,y) = −[log(sum_i Q(y,i)) + log(sum_t Q(t,y))]/2.

For p⊗q this is the original anchor; for native12 it is −log s(y). Using half
the joint pair NLL would halve native supervision and change the comparison;
it is not proposed. A full joint pair NLL for144 would also be another objective.

Use S: C; H: .2 C; A: .2 C−E_Q[R_y]; N: .2 C−V_rho(Q,R_y), rho=1.5.
No anchor, risk, scale, LR or architecture search is added. R and its actual
pixel semantic/quality terms are unchanged. A/N see training labels/R through
their loss only; service sees neither. S is the strong original pure-CE control,
not replaced by the weaker .2 anchor H.

For one shared softmax and batch n, the logit gradients are:

    g_C = (s−onehot(y))/n
    g_Autility = −s*(R_diag−E_s R_diag)/n
    g_Nutility = (tilted−s)/(rho*n), tilted = s*exp(−rho*R_diag)/Z.

For144, the unchanged anchor gradient is
Q(t,i)*[1−.5*1(t=y)/p_y−.5*1(i=y)/q_y]/n; the same categorical utility gradients
apply over144 states. Direct categorical derivatives are required. The existing
`joint_value_and_grad` assumes p⊗q and is unsuitable for either correlated law.
Evaluation may use sparse diagonal12 values or exact expanded Q with the original
requestwise `certainty_equivalent`, and must check parity before freezing.

On native12 with verified identity decoders, joint success is s(y), both-wrong
and wrong-agreement are both 1−s(y), and one-correct/disagreement are zero. This
makes concentration of errors explicit; consistency alone becomes uninformative.

## Operator and implementation consequences

The calculator quotes the existing immutable prices and documents prospective
single-head inventories. Quotes are neither executed kernels nor CPU timings.
For batch n and m outputs, forward MAC=n(202·32+32m), backward MAC=
n(202·32+2·32m). The existing two-head totals are n·7,232 and n·8,000.
For native12 they are n·6,848 and n·7,232; for144, n·11,072 and n·15,680.
The encoder remains dominant; halving head parameters is not halving training.

Native12 has396 fewer active parameters (5.43%);144 has3,960 more (54.34%).
All retain2,496 fixed decoder parameters. Store theta/gradient/two Adam moments,
per-group clocks, nonfinite/clipping checks and all setup/export bytes. The flat
utility uses n·m cells instead of independent n·12² contractions. Full original
R is still retained and billed for honest decoded observations.

`NativeAdam` Python metadata and `hepta_adam_content_v1` C both require **six**
parameter groups. A one-head model has four. It needs a separate, checked ABI
and adapter with identical Adam equations, norm5 clipping, eps1e−8 and independent
per-parameter clocks. Do not fake a second unused head or charge phantom gradients.
All four groups advance each executed joint update; moments start at zero and
decoder moments remain untouched. Compile/allocation/binding costs are real
shared preparation. This analysis has not implemented or benchmarked that adapter.

See `runs/content-joint-architecture-analysis-v1-20261023/analysis.json` for exact
quoted per-step/service inventories and the complete-budget proposal. Future
timing must enclose input/guard/setup, forward, sampling, real PNG/JSON/hash,
return and receipt/export, with recurring versus one-time costs explicitly
attributed. No old component timing supports a complete service win.
