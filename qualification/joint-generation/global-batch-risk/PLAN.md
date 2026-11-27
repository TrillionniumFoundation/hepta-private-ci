# Global64 input/output risk — source-only literal qualification

New explicit mode/profile/schema, fixed64 rows and rho0 or1.5. The wrapper rejects
old group profiles and maps this mode to unchanged aggregate_rows(G=1,K=64).
API accepts row CEs and NEGATIVE MEAN row logit gradients already containing1/64;
its gradient multiplier is64softmax(-rho rowCE). Ordinary rowmean anchor remains
outside this helper; no reward, serving law, numeric guard or derivative changes.
New grouping identity differs from the existing eight content groups of eight.

## Mathematical scope
At fixed observable X=x, policy cannot observe latent Y and reward is fixed:
E_{Y|x} CE_rho(R(Y,A)) <= E_{A~policy_x} E_{Y|x}R(Y,A)
<= max_a E_{Y|x}R(Y,a). Jensen gives the first inequality. A deterministic Bayes
act attains both bounds, because conditional-on-Y output risk vanishes. Across X,
the bound is E_X max_a E[R|X,a], NOT max_a E_{X,Y}R. This shared optimum claim is
only for unrestricted policies without entropy/diversity constraints or anchor.
Current finite softmax/shared network/ordinary CE anchor/optimization are excluded;
no claim NDU is useless in a finite neural training problem follows.

For row CEs ci, eight group CEs Cg and uniform batch:
Cglobal=-log(mean_i exp(-rho ci))/rho
       =-log(mean_g exp(-rho Cg))/rho.
For rho>0: Cglobal <= mean_g Cg <= mean_i ci <= mean_i expected_reward_i.
Relative to mean group risk, outer derivative weight8softmax_g(-rho Cg) emphasizes
hard CONTENT groups as well as hard views. This is a new surrogate, not an NDU bug
repair. At rho0 all three reduce to mean reward. A minibatch log-mean-exp objective
and its gradient are not unbiased estimators of whole-FIT population risk/gradient;
Adam is not guaranteed unbiased. Train independent-output versus coupled serving
mismatch remains. No improvement to the original mean-row evaluation is promised.
If latent Y remains uncertain at fixed X, global-risk Bayes action minimizes
E[exp(-rho R)|X,a], which can differ from expected-reward Bayes action. With perfect
Y identification and free policies even this distinction can disappear.

## Fixed qualification, no scientific data/model
13 literal tests:6 old group risk+3 old integration BYTE EXACT,4 new tests.
Handwritten64 rows in8 groups, legal partial-command maps, heterogeneous fixed
reward tables/targets, deterministic literal logits. Tests compare direct flattened
input x joint-output CE, two-level inner/outer value and gradient, eight both-head
FD coordinates for utility and another eight for utility+.2ordinary anchor;
zero-rho exact gradient parity, constant-row scales exactly1, permutation covariance,
logit-gradient zero-sums, identity separation, shape/nonfinite/mode refusals and
input immutability. Prospective tolerances3e-15 algebraic,3e-8 FD withstep1e-6;
no bitwise claim for differently ordered nonzero-rho reductions. No fixtures run
by producer. Old tests include sampler string inventory only, not actual dataset.

One existing synthetic shared lock, nonblocking/no retry, CPU0 single numerical
thread,5CPU/30wall/512MiB/4MiB; full wait4 even failed/killed child. Source allowlist,
no payloads/descendants/network, no training/model restore/scientific data rows.
All imports/tests/hashing/output included in child measured costs; review/prep and
supervisor tail additional notzero. Independent static review before execution.

## Prospective science only — not admitted by this qualification
A/groupN/globalN x4 originalsourcebases using static grouped64 sampler,300updates,
rho1.5, ordinary anchor.2, unchanged oldFIT calibration and original five gates.
Compute all three aggregations in every arm, count added arithmetic. Require exact
historical4base and8A/groupN digests and complete old metrics. globalN-A and
globalN-groupN each8 unpooled primary contrasts,16 gates, no pooled rescue. Keep
all negative results. No science worker or experiment is included here.
