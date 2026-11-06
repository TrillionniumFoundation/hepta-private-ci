# A pure-information state gate and its decision statistic

Status: internally proved finite reference and designed exact examples.
No new random calibration or confirmation samples are collected. The comparison
to a classical baseline is settled by an identity before sampling. This is not
a new RL algorithm, general unknown-kernel result or real-LLM performance claim.

## 1. Fixed external task, state and real-duration contract

Each deployment has a fresh hidden label `H` with known prior `Bernoulli(1/2)`.
The terminal reward is exactly `1{answer=H}`. It never depends on the observed
state or the number of interventions. No reward is assigned for becoming ready.
The observed state starts locked. There are at most **two** query launches:

- `prepare` costs `c0`, takes deterministic duration `d0>0`, reveals no label,
  and independently of `H` makes the state ready with probability `r`.
- `probe` costs `c1`, takes duration `d1>0`. In the ready state it returns a
  binary label with known orientation and accuracy `p>=1/2`; in the locked state
  it returns a fair coin independent of `H`. It does not change readiness.
- A further prepare in the ready state preserves readiness and gives no
  information. A failed prepare is observed and stays locked.

All fees are nonnegative. Time costs `lambda>=0` per consumed duration unit.
The controller may STOP with a label at any time. An integer cap no larger than
the remaining deadline is selected at launch. Completing at the cap is on time;
otherwise cancellation returns only timeout, consumed cap and unchanged state.
The launch fee is still paid. The deadline is `T`, and `d0,d1,T` are integers
in the executable reference. Query duration is not replaced by query count.
These are declared physical durations in the mathematical model; the reference
does not measure a real model, provider latency or operating-system scheduling.

Let `k0=c0+lambda*d0`, `k1=c1+lambda*d1`. The family has only two unknown
quantities, `r in [0,1]` and `p in [1/2,1]`. These support, symmetry and orientation
restrictions are information supplied to **every** structured method.

## 2. Exact optimum and a genuine lookahead mechanism

**Proposition 1.** If `T<d0+d1`, the optimal value is `1/2`. Otherwise define

\[
\theta=r(p-1/2-k_1)-k_0. \tag{2}
\]

The optimal value over all legal history policies is

\[
V^*=1/2+[\theta]_+. \tag{3}
\]

With STOP preferred on ties, prepare is optimal exactly when `theta>0` and
the full sequence fits the deadline. Its continuation probes after success,
reports the returned label, and stops with a fixed label after preparation
failure. Receding one-step VOI stops immediately and obtains `1/2`.

**Proof.** Before preparation every response is uninformative about `H`.
One query followed by STOP therefore has value at most `1/2`; its nonnegative
fee and elapsed-time cost cannot improve it. An initial locked probe or a
cancelled query leaves only one query and cannot both prepare and obtain a
useful signal. A completed preparation with fewer than `d1` units remaining
also cannot improve terminal accuracy. Such policies are weakly dominated by
STOP. These observations prove the deadline case and the myopic claim.

When the full sequence fits, the only possibly useful initial query is a
completed preparation. On failure, one remaining query cannot obtain useful
information. On success, the last-step comparison is between STOP value `1/2`
and probe value `p-k1`. Thus the best prepared value is
`1/2-k0+r*max(0,p-1/2-k1)`. If the inner gain is nonpositive this is no better
than STOP. If positive its improvement is (2). Comparing with immediate STOP
proves (3). Randomization cannot improve the maximum. ∎

For `c0=.08,c1=.12,d0=d1=1,lambda=.01,T=2,r=1`, the threshold is `p*=.72`.
At `p=.87`, DP obtains `.65` while myopic obtains `.5`; at `p=.57`, both stop.
At `r=.5,p=.87`, DP obtains `.53`; at deadline 1, every law stops optimally.
Higher time prices or launch fees can eliminate the preparation benefit.
The positive case is a deliberately designed mechanism example, not an
independent confirmation result. Its state changes what can be learned,
without changing how a correct terminal answer is scored.

The known contract alone also certifies STOP with **zero calibration samples**
when `k0+k1>=1/2`, because `theta<=1/2-k1-k0<=0`. This proof avoids paying to
identify nuisance parameters in a region where no allowed law changes the action.

## 3. Paid calibration of the decision, not every kernel coordinate

A calibration trial resets the device to locked, instantiates an independently
labeled training task, completes prepare, and completes probe only on success.
Let `S` indicate preparation success and `B` whether the returned probe label
matches the training label. Define `S*B=0` on failure. The statistic

\[
W=S(B-1/2-k_1)-k_0\quad\text{satisfies}\quad\mathbb E W=\theta. \tag{4}
\]

The training label is a paid calibration capability, never the hidden label of
a subsequent deployment. Trials are IID, complete and stationary. Calibration
uses its own sufficient time budget; censoring one and treating it as a full
trial would violate (4). The model does not assume that logged partial traces
or unlabelled deployments provide the same access.

Outside the universal-STOP region, `k1<1/2`; the values of `W` lie in the interval
`[-k0-1/2-k1, -k0+1/2-k1]` of width one. For `n` complete trials with `s`
preparation successes and `b` correct responses,

\[
\widehat\theta_n=\frac{b}{n}-(1/2+k_1)\frac{s}{n}-k_0. \tag{5}
\]

For one fixed, prespecified sample count, Hoeffding's inequality gives

\[
\Pr(|\widehat\theta_n-\theta|>\epsilon_n)\leq\alpha,
\qquad \epsilon_n=\sqrt{\log(2/\alpha)/(2n)}. \tag{6}
\]

For a **prespecified finite** grid of `J` possible sample counts, use
`epsilon_n=sqrt(log(2J/alpha)/(2n))` and a union bound. At any of these checkpoints,
deploy can be certified if `theta_hat-epsilon>0`, STOP if
`theta_hat+epsilon<=0`; otherwise return UNRESOLVED. Stopping adaptively at
these checkpoints preserves simultaneous coverage. An arbitrary stopping time
or an unregistered search across additional cells is not licensed by (6).
The interval argument uses width one, not full-row TV estimation. It assumes the
structured calibration family above; it does not estimate a general joint kernel.

The executable admission rule uses a deliberately conservative rational radius.
For `ell=min{k:2^k>=2J/alpha}`, `log(2J/alpha)<=ell`; it rounds
`sqrt(ell/(2n))` **upward** to a rational with denominator one million using
integer arithmetic. Decisions compare exact rationals. This wider band preserves
(6)'s validity without relying on floating logarithm or square-root rounding.

At a fixed sample count, the simple rule `deploy iff theta_hat>0` has wrong-action
probability at most `exp(-2*n*theta^2)` for either sign of nonzero `theta`.
Its expected deployment regret is at most
`abs(theta)*exp(-2*n*theta^2)`. This follows from the corresponding one-sided
Hoeffding bound and the exact two-policy loss gap `abs(theta)`. At `theta=0`
the deployment regret is zero, but finite-time certification of a unique
optimal action is not claimed. A bounded sampling budget may end UNRESOLVED.

## 4. A mandatory classical baseline gives exact equivalence

The same observations have structured maximum-likelihood estimates

\[
\widehat r=s/n,\qquad
\widehat p=\max\{1/2,b/s\}\ (s>0),\qquad \widehat p=1/2\ (s=0). \tag{7}
\]

**Proposition 2.** For every possible observed count triple `(n,s,b)`, the
direct rule from (5) and exact DP under (7) select the same initial action,
with STOP preferred on ties. They subsequently execute the same policy.

**Proof.** If `s=0`, both improvements are `-k0<=0`. If `b/s>=1/2`, inserting
(7) into (2) gives exactly (5). If `b/s<1/2`, (5) is nonpositive, and clipping
to `1/2` gives `-r_hat*k1-k0<=0`; both stop. The insufficient-deadline and
universal-STOP cases are known to both methods. Whenever either deploys, the
unique useful continuation in Proposition 1 is the same. ∎

Giving both methods the same confidence band, checkpoints and accounting makes
their stopping decisions, acquired prefixes and deployment utilities identical
on every sample path. This is stronger than an inconclusive finite comparison.
No positive statistical advantage over that baseline can be established by
collecting more seeds from this class. Any implementation-time difference would
need its own measured computation experiment; the formula alone proves none.

An unrestricted full-row estimator can waste calibration by ignoring supplied
structure, but comparing only against it would understate the available baseline.
The prospective random superiority comparison is therefore cancelled before
sampling. The exact known-law examples and deterministic count enumeration
remain useful mechanism qualification, with zero random data acquisition.

## 5. Acquisition costs remain in the lifecycle objective

Let a reset cost `cR` and take duration `dR`, and let each training label cost
`cL`. With the same launch/time prices, `n` complete trials with `s` successes
incur exactly

\[
C_{\rm cal}=n[c_R+c_L+c_0+\lambda(d_R+d_0)]
              +s[c_1+\lambda d_1]. \tag{8}
\]

Fees for failed preparation, labels and resets are included. Actual additional
validation, retries, hardware compute and engineering costs must be added to
form `C_total`; unpriced resources do not become free. A positive conditional
certificate relative to no-data STOP at a **prespecified** deployment count `M`
requires `theta_hat-epsilon-C_total/M>0`. Correctly learning STOP can still
lose lifecycle value because calibration has already been paid for. An assumed
future deployment count is not a realized saving. The present qualification
collects no trials, so (8) is a formula, not an actual invoice or simulated bill.

The companion finite-catalog analysis addresses identification of the deployment
action and its information-cost lower bound under further assumptions. It must
not be conflated with proving utility-optimal calibration at finite `M`, or
with a hard wall-clock guarantee for an uncapped sequential test.

## 6. Scope relative to primary prior work

[Cheng and Huan, 2026 revision](https://arxiv.org/html/2509.21734v3) already jointly
optimize sequential design and stopping and permit a physical state component.
Their framework and continuation-value analysis prevent claiming that merely
adding state or STOP is original. The result here is a scoped exact diagnostic
and a baseline-equivalence certificate, not a priority claim for those ideas.

[Golovin and Krause, 2011](https://ocs.aaai.org/Library/JAIR/Vol42/jair42-012.php)
give greedy guarantees under adaptive submodularity. Here a preparatory action
can increase a later probe's information value from zero to a positive amount.
No diminishing-return condition or greedy guarantee is assumed without proof.
The exact constructions supply their own proof instead of borrowing that guarantee.

The bounded-mean tail bound in (6) is the classical inequality of
[Hoeffding, 1963](https://doi.org/10.1080/01621459.1963.10500830), not a new
concentration result.
