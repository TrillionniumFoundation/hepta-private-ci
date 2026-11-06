# Sharp finite deadline in the existing two-member calibration catalog

This specializes classical binary minimax testing. All laws are supplied;
learning identifies which member is present. It is not a new testing method.
The inherited members are p0=57/100 and p1=87/100. A complete, labeled,
regenerative calibration macro returns Bernoulli(p_h). Its reset, label,
prepare, probe and time bill is 3/10; its duration is three model time units.
Partial macros, parallel calibration and uncharged first resets are excluded.
Calibration labels concern training cases, not future deployment labels.

## Exact risk, including randomized terminal answers

For a cap of n complete macros let

`a_j = choose(n,j) p0^j (1-p0)^(n-j)` and
`b_j = choose(n,j) p1^j (1-p1)^(n-j)`.

There is an integer k and a probability

`r = [sum_(j<=k) b_j - sum_(j>k) a_j] / (a_k+b_k)` in [0,1].

Choose answer 1 above k successes, answer 0 below it, and answer 1 with
probability r at equality. Both conditional error probabilities equal

`R_n = sum_(j>k) a_j + r*a_k`.

For the least-favorable prior `lambda=b_k/(a_k+b_k)`, monotonicity of the
binomial likelihood ratio implies that this rule minimizes the weighted error.
Its exact lower bound is

`sum_j min(lambda*a_j, (1-lambda)*b_j) = R_n`.

Every rule's maximum conditional error is at least its lambda-weighted error,
so the equal-error rule attains the minimax value. Any adaptive rule stopping
by n samples is a randomized function of n pre-drawn observations: provide
the same stream and ignore its unused suffix. It therefore cannot beat the
full-sample minimax bound. This proves necessity for all permitted stopping
rules, and the threshold rule proves sufficiency. No oracle hidden-member
policy is used.

All quantities are Fractions. `binary_deadline.py` requires rational input;
passing binary floating-point probabilities is rejected. The exact weighted
lower bound and two exact conditional errors are checked for every reported n.

| Maximum complete macros | Exact-model minimax error (decimal display) | Uniform 5% possible? |
| ---: | ---: | --- |
| 13 | 0.10493615472434893 | No |
| 22 | 0.050491483634380684 | No |
| 23 | 0.048835172241606405 | Yes |

The optimum is nonincreasing in n because a rule may ignore added observations.
Thus 23 is the smallest feasible integer cap, requiring a maximum of 69 model
time units under this complete-macro contract. It does not mean 69 measured
seconds or include unmodeled controller/serving time. All caps 0 through 30 are
retained. The prior reference's 13-sample Bayes error 0.09848678102415421 used
a fixed equal prior and remains correct: worst-conditional minimax error is a
different, larger quantity.

## Executable earlier stopping and its cost boundary

An equivalent rule can stop before n when every possible future completion
would give the same deterministic answer. At i observed samples and s successes,
stop with answer 1 if s>k, or answer 0 if s+n-i<k. Otherwise continue, using the
same terminal randomization at equality. The early and full rules give the
same answer on every completed stream with the same randomization. A rational
recursion computes both conditional errors and expected sample counts.

At n=23, its expected macro counts are approximately 15.9899552141 and
20.5097313845. Fully paid expected costs are 4.7969865642 and 6.1529194153.
The worst possible bill is 6.9 and worst model time is 69. These are synthetic
resource units, not a provider invoice. They exclude unpriced implementation,
model acquisition, validation and hardware expenses.

**This early wrapper is not asserted to minimize expected cost.** An independent
review supplies a stricter comparator at n=1: our wrapper always samples and
pays .30. Instead stop immediately with answer 0 with probability 11/36;
otherwise sample once and follow the observation. The two errors remain 19/48,
but expected samples are 25/36 and the fee is 5/24. Thus an early-versus-fixed-n
cost reduction is not evidence of advantage over all same-information rules.
The general sequence LP includes such randomization; its finite tree becomes
large at long horizons. No near-information-cost efficiency of the new wrapper
is claimed, and no prior negative lifecycle endpoint is rewritten.
