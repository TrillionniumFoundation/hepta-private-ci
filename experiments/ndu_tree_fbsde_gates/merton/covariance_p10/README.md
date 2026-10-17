# P10 — paired original-Qwen empirical covariance and Merton surrogate (DENY_ALL)

**DRAFT · RESEARCH_ONLY · SHADOW_ONLY · DENY_ALL · NO MAIN MERGE · NO MODEL PROMOTION.**

Strict child of P9 PR #2650, exact parent `38992e4977193aba096def444f59960b78ad723d`. Only **new** research Python/README and a **read-only** workflow are admitted; original P5–P9, native NDU/Neuron/CNS, protected `main`, selected weights, `blocking-ci`, ModelWorker and FinalUse remain unchanged. This study opens **no new original model calls**, has no deployment or runtime right, and cannot establish any training efficacy.

## Why P10 exists

P1–P9 optimize mean empirical action utility and a bounded risk preference, but no original experiment has explicitly estimated a **joint paired cognition-return covariance matrix**. Using an imagined independent covariance or dividing arbitrary conditional regression moments by `dt` would be unsound. The only original evidence already available for a bounded P10 study is the successful P5 source/model/postseal [GitHub Actions run #39000773484](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39000773484), with 48 distinct pretrained Qwen3 TRAIN forwards (16 examples × direct/reason/verify), 112 independently paid held policy forwards, 32 paid thinking controls, and separate labels and auditor.

The P10 code requires exactly the **seven raw file SHA256 values** already frozen by P7 #2620. It then independently derives the TRAIN paired-data covariance and shadow allocations, verifying the exact original run before opening held-out publisher labels. The original research status is **historically public**, not a prospective independent family/window design.

### What exactly is modeled

For each of 16 TRAIN rows, compute observed net incremental cognitive payoff (success minus registered token tariff) relative to direct:

\[
D_i^a=(\mathbf{1}[\widehat Y_i^a=Y_i]-\mathbf{1}[\widehat Y_i^{direct}=Y_i])
 - (C_i^a-C_i^{direct})/2048, \quad a\in\{reason,verify\}.
\]

All `Y_i` are **original TRAIN publisher labels**, never HELD labels. `C_i^a` is that original full input+output token count, not an invented billable or simulated token. Compute exact rational sample mean and unbiased empirical 2×2 covariance. A separate empirical least-squares check solves `Z Sigma = B` **only when the sample covariance is nonsingular**. Its `Z` is *not* a conditional BSDE integrand, a model parameter gradient or a proof of FBSDE well-posedness.

As a deliberately narrow classical-Merton-inspired **linearized exposure surrogate**, enumerate 153 possible allocations of 16 public held tasks to direct, reason or verify. For exposure fractions `w=(n_reason/16,n_verify/16)`, rank:

\[
J_\gamma(w)=\hat\mu^\top w-\frac{\gamma}{2}w^\top\hat\Omega w,
\quad w\ge0,\quad w_1+w_2\le1.
\]

Here `gamma=2` is a frozen **research** risk coefficient. Controls: direct-only, risk neutral (`gamma=0`), diagonal-only (ablation), full empirical covariance, and an independently reproduced **ordinary same-objective** optimizer. Exact rational tie-breaking favors less intervention, then verify rather than reason. `wᵀΣw` is a paired-return **surrogate**, not the realized variance of a randomized mutually exclusive action; this is not a global Merton solution for the real Qwen process.

Policy exposure is frozen using TRAIN and public held IDs **before** opening HELD gold. In this historical retrospective evaluation, this computational separation cannot rewrite the chronology or make P5 prospective. A selected action is supported only if a genuine P5 separately paid *same held task/action* trace exists. If any selected action lacks a paid original result, the full-arm held accuracy and cost fields remain `null`; it cannot be imputed from a critic, a synthetic world model or another task. **All 192 original P5 forwards remain paid** regardless of the shadow allocation.

## Executed original data and exact-result ceiling

On the exact original P5 TRAIN file, the incremental correctness means without token penalty are **reason −3/16** and **verify +1/8**. After the registered input+output token tariff, exact net incremental means are `[-59/256, 239/2048]`; the unbiased covariance of those net gains is:

```
[[13/80, 11/120],
 [11/120, 1/4]]
```

Determinant is positive and the empirical algebraic regression returns `[-1, 0]`, but **these are only 16 historically public TRAIN examples with correlated source structure**, not a calibrated expected return or a neural stochastic FBSDE. Under the declared finite surrogate, the full covariance and ordinary matched objective both choose **0 reason + 4 verify + 12 direct**, and diagonal happens to agree. The neutral optimizer requests 16 verify. Original independent reviewer confirms that **14/16** chosen covariance actions and only **4/16** neutral actions have available physically paid held calls; full selected performance is therefore **unavailable for both**. Only the direct-only policy has complete 16/16 original action support (5/16 correct, 2,155 physically self-metered serving input+output tokens). No proven NDU task/cost lift, realized compute saving, prospective evaluation, independent signer or hardware-energy attestation exists.

## Exact replay (standard library, Python 3.13)

Source-only falsifications from the repo checkout:

```bash
D=experiments/ndu_tree_fbsde_gates/merton/covariance_p10
export PYTHONPATH="$D"
python3 -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -m compileall -q "$D"
```

The dedicated read-only workflow downloads **only P5 run 39000773484** and executes the already-independent P7 original 192-call raw/journal gate. Then:

```bash
python3 "$D/portfolio.py" --evidence /tmp/p10-origin --output /tmp/p10-frozen.json
python3 "$D/independent_audit.py" --evidence /tmp/p10-origin \
  --frozen /tmp/p10-frozen.json --output /tmp/p10-independent.json
```

The P10 independent audit shares no P10 proposer import. It reconstructs the paired original sample, source identity, full finite grid, all risk parameters, plan seal, same-profile parity, actual original held action support and cost. It rejects re-sealed forged allocations, mean/covariance changes, future label leakage, missing paid calls and false complete-coverage claims. Its hash pins prove the uncompressed original file **bytes** within the GitHub artifact trust boundary, not independent custody outside GitHub. Artifacts expire; missing evidence is unavailable and cannot be manufactured.

The only adoption disposition is **`RESEARCH_ONLY_NO_PROSPECTIVE_NDU_OR_COST_LIFT`**. Do not merge to `main`, select model weights, bypass `blocking-ci`, issue authority or reinterpret historical P5 results.
