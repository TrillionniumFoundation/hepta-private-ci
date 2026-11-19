# Fixed bidirectional conditional-risk experiment (before execution)

## Motivation and changed estimand

Serving-law alignment improved both additive and joint-NDU training versus raw
training, but NDU's strict greedy-text nonregression failed in one seed. Removing
constant-gradient rows did not resolve that gate; no sampling/weight tuning follows.
Earlier risk decomposition implicated class terms, but was not a causal proof.
This is a prospective direction test, not a claim that risk aversion causes errors.

Use the same shared encoder, two heads, fixed learned decoder, explicit transport
service, aligned semantic-mass anchor, finite generated RGB train and validation.
Only the training utility changes. For the pulled-back actual reward table R':

- A: E[p*q R'].
- J: original joint CE = -log sum_ti p_t q_i exp(-rho R'ti)/rho.
- T: text-neutral V = sum_t p_t[-log sum_i q_i exp(-rho R'ti)/rho].
- I: image-neutral V = sum_i q_i[-log sum_t p_t exp(-rho R'ti)/rho].

T is the proposed mechanism, I a prespecified reverse-direction control. Both are
valid explicit scalar objectives, not a nonconservative splice of head gradients.
They are neither original joint NDU nor an STE or original-objective correction.
For rho>0, J<=T<=A and J<=I<=A by Jensen. Their order can matter; no general order
between T and I, and no greedy accuracy/Adam unbiasedness guarantee is asserted.
The same independent product serving law and actual decoder reward remain in force.
All evaluation rho scores remain ORIGINAL JOINT CE at rho1.5, not the new surrogate.

## Freeze and common work

Two fixed preadaptation bases, seeds11/23. Four objectives A/J/T/I x two seeds =
8 cells. Every arm:300 updates,batch64,lr.003,anchor.2,rho1.5,original norm clip5
and Adam,full sampling of all1560 train rows. No new weight,margin or hyperparameter.
Use exactly original seed+9000 row/full-low mask sequences, precomputed before any
model restore; no outcome-based selection. All4 old utility branches,both anchors,
both new conditional utilities and the same extra base forward execute every arm.
Extra conditional arithmetic is charged even to A/J controls. Distinct mode names
in the final identity. The4 A/J final digests must reproduce prior aligned finals.

All8 finals are fixed and hashed BEFORE validation is generated. No TEST access,
adaptation-model selection or new model checkpoints. Decoder/base tensors immutable.
Train260 groups/1560 rows and validation86 disjoint groups/516 rows,full+low channels.
Primary312 rows have1or2 explicit attributes; report all rows/channels too.

## Unchanged primary requirements

For BOTH seeds and BOTH T-J and T-A, the partial-command macro(full,low) contrast
must have original joint-CE gain>=.005; correct-text mass,greedy-text accuracy,joint
success changes>=-1e-10; actual pixel MSE increase<=1e-10. Any failed condition fails
the overall gate. I-J and J-A are diagnostic only and cannot replace the primary
direction. All arms,all contrasts and failures are retained. No tuning or rerun to
rescue a close threshold. Reused validation is exploratory,not independent evidence.

## Literal qualification and bounded execution

Eight literal tests: central logit differences both directions including small rho;
rho0 exact A parity; modality-swap identity; J<=T/I<=A and non-equivalence; degenerate
outer policy joint parity; constant rewards/zero support; transported-law identity
plus complete anchor gradient; invalid-input rejection and input immutability.
The existing qualified transport/anchor helpers are copied byte-identically.

One completely waited,CPU0,single-thread child under the existing NEW synthetic-only
shared lock; refusal stops.20CPU/90wall/512MiB/4MiB limits,no descendants/network.
Exact source whitelist and2base payload paths. Expected2restores,8clones,2400updates,
7220forward batches/471120rows,2decoder observations/24images,20scalar-vector serving
checks.8tests execute before model restoration. Failure retains receipts,no retry.
Whole wait4 CPU,user/system,wall,RSS recorded. Per-arm train/evaluation CPU recorded.
Inherited base preparation is reported,not free; source/review/supervisor-tail costs
are additional unknown,not zero. Equal update counts/common caps do not establish
equal ACTUAL total spend. No original digit materials/lock have been recovered.
