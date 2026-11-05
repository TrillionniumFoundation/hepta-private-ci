# Decision-relevant paid identification: a finite reference theorem

Status: research reference, 2026-11-05. This is a task-specific specialization of established sequential change-of-measure and controlled-sensing arguments. **It is not a claim of a new lower-bound technique, a new general RL algorithm, or a lower-bound guarantee for learned NDU/JAC critics.** The narrow theorem is useful because it gives the next mechanism experiment a falsifiable denominator and explicitly separates identification, real time, and net external reward.

## 1. Frozen external contract and information pattern

Let the unknown environment be `h` in a finite set `H`. A terminal operational decision is `d` in a finite set `D`; its externally fixed payoff is `u_h(d)`. Each hypothesis has a unique optimal decision

\[
d^*(h)=\arg\max_{d\in D}u_h(d).
\]

An internal intervention/query `q` belongs to a finite set `Q`. At a declared reset state it returns a fresh observation with known conditional law `P_h^q`. The reset assumption means that, conditional on `h` and the chosen query, its outcome is independent of the preceding observations. Each query costs `c_q>0` and takes deterministic physical time `τ_q>0`. All laws have common finite support with positive masses. These assumptions give finite, bounded log likelihood ratios and exclude free informative queries.

A strategy chooses queries from the observed history and independent internal randomization, stops at an almost surely finite stopping time `N`, and emits a decision `d_hat`. It cannot observe `h`, future outcomes, or the validation oracle. Query sampling, failed attempts, switching, and stopping must use the declared information interface. A reset intervention is not a free counterfactual pair: a paired design must justify both obtainable outcomes and pay its actual costs.

The correctness requirement is **decision relevant**:

\[
\Pr_h\{\widehat d\ne d^*(h)\}\le\delta,
\qquad h\in H,\qquad 0<\delta<1/2.
\]

Hypotheses with the same optimal operational decision need not be distinguished. Write

\[
\operatorname{Alt}_D(h)=\{g\in H:d^*(g)\ne d^*(h)\}.
\]

A harmless nuisance coordinate can therefore remain unidentified. This equivalence is relative to the frozen terminal task. If an internal variable changes future legal decisions, resources, the external payoff, or the query law, it cannot automatically be discarded as a nuisance.

Correct identification and optimal paid utility are different objectives. A confidence requirement can rationally cost more than the value of a decision. The next sections connect them only under explicitly stated conditions.

## 2. Cost and clock lower bound

Let `N_q` be the number of completed uses of query `q`, and set

\[
D_{hg}^q=\operatorname{KL}(P_h^q\|P_g^q),
\qquad k_\delta=\operatorname{kl}(1-\delta,\delta)
=(1-2\delta)\log\frac{1-\delta}{\delta}.
\]

Assume `E_h N<∞`. Every uniformly `δ`-correct strategy satisfies, for each decision-changing alternative,

\[
\boxed{\quad
\sum_q E_h[N_q]D_{hg}^q\ \ge k_\delta,
\qquad g\in\operatorname{Alt}_D(h).
\quad} \tag{1}
\]

Consequently expected spending is bounded below by the explicit linear program

\[
E_h\!\left[\sum_{k=1}^N c_{q_k}\right]
\ge
\min_{n_q\ge0}
\left\{\sum_q c_q n_q:
\sum_q n_qD_{hg}^q\ge k_\delta\;
\forall g\in\operatorname{Alt}_D(h)\right\}. \tag{2}
\]

The same conclusion holds for elapsed query time by replacing `c_q` with `τ_q`, or for a prespecified resource scalarization `r_q=c_q+λτ_q>0`. A chosen scalarization is a declared evaluation convention; it is not automatically equivalent to exponentially discounted return.

An equivalent information-per-resource form is

\[
I_h^r=
\max_{w\in\Delta_Q}\min_{g\in\operatorname{Alt}_D(h)}
\sum_q w_q\frac{D_{hg}^q}{r_q},
\qquad
E_h R_N\ge\frac{k_\delta}{I_h^r},
\quad R_N=\sum_{k=1}^N r_{q_k}. \tag{3}
\]

Here `w` denotes resource fractions, not query-count fractions. If `Alt_D(h)` is empty, no information is required and the lower bound is zero. If some decision-changing alternative is observationally identical for all legal paid queries, no finite-cost uniformly correct strategy with `δ<1/2` exists.

### Proof

Fix `h,g`. The same history-dependent sampling rule is used in both environments, so its conditional query-choice probabilities and independent randomization cancel in the likelihood ratio. For a stopped transcript,

\[
L_N^{h,g}=\sum_{k=1}^N
\log\frac{P_h^{q_k}(Y_k)}{P_g^{q_k}(Y_k)}.
\]

The chain rule, conditional expectation, and bounded-increment optional stopping give

\[
\operatorname{KL}(\mathcal L_h(\text{transcript})\|
\mathcal L_g(\text{transcript}))
=E_h L_N^{h,g}
=\sum_q E_h[N_q]D_{hg}^q.
\]

One can justify the stopped identity by first truncating at `N∧m`, applying the finite transcript chain rule, and taking the increasing information limit. Bounded log likelihood increments and `E_h N<∞` justify the expectation limit. Include the terminal decision in the transcript; any extra randomized decision rule is a common Markov kernel and does not increase relative entropy.

Apply data processing to the event `A={d_hat=d*(h)}`. Uniform correctness implies `P_h(A)≥1−δ` and `P_g(A)≤δ` for `g∈Alt_D(h)`. The binary divergence is minimized at these boundary probabilities, giving (1). Counts `n_q=E_hN_q` are feasible for the program in (2). For (3), normalize `w_q=r_q E_hN_q/E_hR_N`; (1) implies

\[
\frac{k_\delta}{E_hR_N}
\le\min_g\sum_qw_qD_{hg}^q/r_q\le I_h^r.
\]

This proves the claims. ∎

### Hard deadline and budget obstruction

If every realized path stops by a hard time `T` and spends at most `B`, its expected query counts must satisfy

\[
\sum_q\tau_q n_q\le T,\qquad
\sum_qc_q n_q\le B.
\]

If these inequalities and all constraints in (1) are jointly infeasible for any possible true hypothesis, a uniformly `δ`-correct policy satisfying those hard resource limits is impossible. This is a necessary condition, not a sufficiency theorem: fractional expected counts ignore integer choices and pathwise fluctuations.

With one query, `N≤floor(T/τ)` on every path. Hence

\[
\lfloor T/\tau\rfloor D_{hg}<k_\delta
\quad\Longrightarrow\quad
\text{the specified deadline and correctness requirement cannot both hold.}
\]

An algorithm should expose this failure rather than silently make a certification claim after timeout. A timeout may still return the best current operational decision; its correctness status must reflect the expired certificate.

### Stateful and random-duration scope

For controlled nonresetting kernels the general chain rule contains history-dependent conditional divergences, not stationary `N_q D_{hg}^q`. For random durations, the observable outcome must include timing, failure, censoring, and any available completion information; duration can itself reveal the hypothesis. A bound that drops that information can be false. Parallel tools additionally require scheduling and overlap accounting: elapsed time is not generally the sum of query times. None of those extensions is claimed by (2) without a new model and proof.

## 3. A matching finite binary reference, with an explicit overshoot term

Take `H={−,+}`, terminal decisions `D={−,+}`, and for query `q`

\[
P_+^q=\operatorname{Ber}(p_q),\qquad
P_-^q=\operatorname{Ber}(1-p_q),\qquad 1/2<p_q<1.
\]

Then both directed divergences equal

\[
D_q=(2p_q-1)\log\frac{p_q}{1-p_q},
\quad M_q=\log\frac{p_q}{1-p_q}.
\]

Fix a resource price `r_q>0` and let `q*∈argmax_q D_q/r_q`, so `I*=D_q*/r_q*`. Repeatedly use `q*`. Let `S_n` be the cumulative log likelihood ratio of `+` against `−`, and stop when

\[
S_n\ge b\quad\text{or}\quad S_n\le-b,
\qquad b=\log(1/\delta).
\]

Choose the corresponding sign. This classical sequential probability ratio test is uniformly `δ`-correct and satisfies, under either hypothesis,

\[
\boxed{
\frac{k_\delta}{I^*}
\le E_hR_N
\le\frac{\log(1/\delta)+M_{q^*}}{I^*}.
} \tag{4}
\]

Therefore its resource ratio to the information lower bound is at most

\[
\frac{\log(1/\delta)+M_{q^*}}{k_\delta}\longrightarrow1
\quad\text{as }\delta\downarrow0.
\]

This is an asymptotically sharp benchmark for the explicitly symmetric known-law binary class. It is not a claim for arbitrary finite hypotheses, unknown observation laws, changing internal state, finite deadlines, learned models, or a general discounted utility optimum.

### Proof

Under `−`, `exp(S_n)` is a nonnegative likelihood-ratio martingale starting at one. The probability of ever reaching `exp(b)` is at most `exp(−b)=δ`; hence the chance of choosing `+` under `−` is at most `δ`. Applying the same argument to `exp(−S_n)` under `+` gives the other error bound.

Under `+`, the IID bounded increments have positive mean `D_q*`. If `N>n`, then `S_n<b`. For sufficiently large `n`, a bounded-increment concentration bound makes this probability exponentially small, so `E_+N<∞`. The corresponding statement holds under `−`. At stopping, `S_N≤b+M_q*`. Wald's expectation identity yields

\[
D_{q^*}E_+N=E_+S_N\le b+M_{q^*}.
\]

Apply the symmetric argument under `−`, multiply by `r_q*`, and use (3) for the lower bound. ∎

## 4. A rigorous bridge to elapsed-time net reward in this tiny model

Now give a correct terminal decision fixed external reward one and an incorrect decision reward zero. Take the symmetric prior, constant query duration `τ`, query admission charge `c`, and elapsed-time discount rate `ρ≥0`. The realized utility of a stopped test is

\[
U=e^{-\rho\tau N}\mathbf1\{\widehat d=h\}
-c\sum_{k=0}^{N-1}e^{-\rho\tau k}. \tag{5}
\]

Costs are charged when queries start; the terminal payoff arrives when the final query completes. No separate fee proportional to the same discount loss is added. If a genuine independent time rent or computing charge is included, its economic meaning and units must be stated separately.

For the test in Section 3 with a single chosen query, put

\[
\bar n=\frac{\log(1/\delta)+M}{D}.
\]

Then

\[
E_hU
\ge \exp(-\rho\tau\bar n)-\delta-c\bar n. \tag{6}
\]

Indeed, `E[e^(−ρτN)1_correct]≥E[e^(−ρτN)]−P(error)`, Jensen gives `E[e^(−ρτN)]≥e^(−ρτ E N)≥e^(−ρτ nbar)`, and total discounted charges are at most `cN`. Thus a sufficient condition for net improvement over immediate uninformed choice (Bayes value `1/2`) is that the right-hand side of (6) exceed `1/2`.

This bridge is deliberately conservative. A fixed-confidence policy can lose to a Bayes-optimal stopping rule, and closeness to (4) does not itself establish utility optimality. The exact same-information belief-state DP remains a required comparator.

### Reproducible numerical instance, not a real-tool experiment

The companion NDU manuscript's [verification script](https://github.com/TrillionniumFoundation/NDU/blob/30145183b080012f4a3f88a2606856db459ae540/research/2026-11-05-decision-identification/verify_corrections.py) evaluates the absorbing random walk by a finite linear system, without Monte Carlo; its [numerical receipt](https://github.com/TrillionniumFoundation/NDU/blob/30145183b080012f4a3f88a2606856db459ae540/research/2026-11-05-decision-identification/theory_verification.json) is pinned to the same correction commit. Use `p_+=0.7`, `p_−=0.3`, `δ=0.05`, `c=0.005`, `τ=1`, and `ρ=0.01`. The time unit is a specified model unit, not measured tool latency.

| Quantity | Value |
|---|---:|
| KL per query | 0.3389191442 |
| Absolute log likelihood increment | 0.8472978604 |
| Threshold in random-walk steps | 4 |
| Exact error probability | 0.0326349718 |
| Information lower bound on `E N` | 7.8189595570 |
| Exact `E N` | 9.3473005641 |
| Overshoot upper bound on `E N` | 11.3390765916 |
| Actual expected cost / information lower bound | 1.1954660330 |
| Conservative discounted net utility lower bound | 0.7861063325 |
| Exact discounted net utility | 0.8385461324 |
| Immediate uninformed Bayes utility | 0.5 |

At hard deadline `T=5`, at most five observations are possible; maximum transcript information is `5D≈1.694596`, below `k_δ≈2.649995`. No strategy in this one-query model can meet the stated uniform five-percent error requirement by that deadline. The unlimited-time positive net reward result must not be reused as a deadline guarantee.

## 5. Minimal nonidentifiability and decision-sufficiency controls

**Nonidentifiability.** Let `H={−,+}`, every legal free observation have the same law under both models, and optimal terminal decisions differ. Any policy using only those observations has identical decision distribution in both worlds. If it selects `+` with probability `p`, the two errors are `p` and `1−p`, so maximum error is at least `1/2`. A paid intervention with different observation laws can remove this obstacle. A hidden-state or gradient learner receiving the same observations cannot do so merely through architecture.

**Decision-irrelevant nuisance.** Let `H={(z,n):z,n∈{0,1}}` and terminal reward depend only on selecting `z`. One query identifies `z`; another identifies independent `n`. Full model entropy rewards both. Decision-relevant identification requires only the first. A policy buying the nuisance query at positive cost loses net utility without improving the chosen external decision. This is a test of task alignment, not evidence of a new information-theoretic principle.

## 6. Prior work and claim boundary

The central ingredients already have direct precedents:

- Kaufmann, Cappé, and Garivier, *On the Complexity of Best-Arm Identification in Multi-Armed Bandit Models*, JMLR 17 (2016), gives the adaptive stopped change-of-measure lower-bound machinery. [Primary paper page](https://www.jmlr.org/beta/papers/v17/kaufman16a.html).
- Nitinawarat, Atia, and Veeravalli, *Controlled Sensing for Multihypothesis Testing*, IEEE TAC 58(10), 2013, studies causal observation control and sequential testing. [Author-hosted paper](https://vvv.ece.illinois.edu/papers/journal/niti-atia-veer-tac-2013.pdf).
- Nitinawarat and Veeravalli, *Controlled Sensing for Sequential Multihypothesis Testing with Controlled Markovian Observations and Non-Uniform Control Cost*, Sequential Analysis 34(1), 2015, already includes controlled memory and nonuniform accumulated costs. [Primary preprint](https://arxiv.org/abs/1310.1844).
- Garivier and Kaufmann, *Optimal Best Arm Identification with Fixed Confidence*, COLT 2016, characterizes information allocation and Track-and-Stop in its stated bandit class. [PMLR page](https://proceedings.mlr.press/v49/garivier16a.html).
- Kanarios, Zhang, and Ying, *Cost Aware Best Arm Identification*, RLJ 4, 2024, derives a cost lower bound and asymptotically matching CTAS; heterogeneous testing cost is already an explicit primary objective. [RLJ page](https://rlj.org/papers/kanarios2024cost).
- Harding and Kandasamy, *Balancing Performance and Costs in Best Arm Identification*, NeurIPS 2025, balances observation cost with a terminal performance penalty and gives DBCARE bounds. A net-decision-cost objective alone is therefore not a novel distinction. [Proceedings page](https://papers.nips.cc/paper_files/paper/2025/hash/b0dfe8236981ba84b4d98a7ed0426f0b-Abstract-Conference.html).

The bounded result here is an accountable research reference. A publishable NDU contribution would still need to solve a presently unclosed extension, such as useful finite-sample control of an estimated nonlinear continuation kernel under paid state-changing interventions, joint duration/censoring information with actual deadlines, or an independently measured net-utility advantage under the same information and full computational budget. No such extension is claimed proved by this document.
