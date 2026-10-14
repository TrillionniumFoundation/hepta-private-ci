# Actual partial-text acquisition and finite NDU control

This additive profile continues #1550 at
`20264fd25be021d2b935a9d3061a40f047a5bdb8`. It keeps all historical experiments,
V1/V2/V3 controls and the canonical qualification reviewer unchanged. The new
question is when to pay for more semantic computation, not how to re-evaluate a
known Boolean formula. There is no new owner, model selection or release path.

## Original labels; an explicitly designed observation process

Use the same SHA-pinned CLINC150 publisher files and eight banking intents not
used in the four-intent composition tasks: freeze_account, routing, pin_change,
pay_bill, interest_rate, transfer, balance, report_fraud. First 60 training rows
per class fit a shared Head; the remaining 40 fit the observation law. The first
10 validation rows per class select simple controllers; the next 10 are reported
without selection. All 30 original test rows per class are held for scoring.
This yields 480/320/80/80/240 rows. Original text hashes must be distinct within
and across these splits; overlap rejects instead of filtering the test results.
No Boolean/composite truth labels are generated. Original annotation can still
be imperfect, and public pretraining contamination is not ruled out.

The designed views are the first three whitespace-delimited words, the last
three, and full unchanged text. The initial view is mandatory; either remaining
view costs .02/.04 declared utility units. Short texts and overlapping views are
retained. This is offline partial-information acquisition, NOT a fresh user reply,
a live environment observation or a genuine future calendar window. Reading a
full text includes its suffix, but a router receives only each view's Head symbol;
asking the suffix Head can add computation information without new world evidence.

Two explicit backends share the same 12,456-parameter gated Head and task design:
`hashing_reference_v1` is a deterministic untrained 384-dimensional signed lexical
hashing encoder; `mmbert` uses the existing physical pinned mmBERT loader. There
is no silent backend fallback. Ninety-six AdamW steps at .003 fit the Head using
only fit labels and all three fit views. Normalization uses only fit vectors.
Encoder and Head are frozen throughout kernel fitting, selection and evaluation.

## Joint observations, not repeated counting of correlated evidence

A positive smoothed empirical law P(class,s_initial,s_suffix,s_full) is fitted on
320 disjoint kernel rows, with additive .01 pseudo-count per cell. There are eight
class labels and eight argmax symbols per view, 4096 cells. This is a coarse,
sparsely supported learned law, NOT the true conditional distribution. Confidence
probabilities and raw text are not additional router channels; all policies get
the same symbol history and fitted law. Distinct view likelihoods are NOT
multiplied as though their errors were conditionally independent.

`ViewPort` calls the classifier only after a legal read is selected. A policy
receives no test ID, text, label or future-view result. Each test arm separately
performs its requested Encoder/Head forwards; no other arm's full-text result is
silently reused. Plans, immutable model bindings, per-request view text hashes,
probabilities, symbols, action histories and CPU measurements are retained. The
label file is scored only after every test prediction file is closed and synced.
This in-process design is not OS isolation, independent observation attestation,
native scope/final-use authorization or a production journal.

## Finite BSDE and independently checked continuation policy

Fixed terminal utility is +1 for a correct class, -1 for a wrong class, and zero
for abstention. No-change here is the `initial_only` research control, NOT a claim
about the currently deployed Hepta model. All arms can abstain; coverage and
accepted-answer error are reported together with score minus actual read charges.
The main objective is expected utility. The separately registered risk arm uses
rho=.5 and conditional entropic certainty equivalent

    CE_rho(v;p) = -log(sum_j p_j exp(-rho*v_j))/rho,
    CE_0(v;p) = sum_j p_j*v_j.

For a read with future optimal values v_j, local Y=CE_rho(v;p)-cost. Put
mean=sum p_j v_j, Z_j=v_j-mean, M=e_observed-p, f=Y-mean. Then

    E(Z)=0,   v_j = Y - f + Z_j.

For rho=0, f=-cost. For rho>0, f=CE_rho(v;p)-mean-cost is a nonlinear conditional
risk generator. Every local branch identity is checked, without choosing the
largest chance outcome. The centered-one-hot driver is singular in ambient
coordinates: the mean-zero gauge identifies this finite representation. It does
NOT replace the native full-rank covariance pilot or authorize a pseudoinverse.

On this finite acyclic horizon, backward induction gives the unique value of a
fixed nonanticipative policy, and maxima over the admitted actions give the finite
optimal value. Fixed-rho CE is cash additive and time consistent: exponentiating
the one-step recursion and iterating conditional expectation gives the same CE
of the whole terminal reward minus realized acquisition costs. This is why an
independent oracle can enumerate whole contingent policies directly from the
original joint masses. With K observation symbols there are 1+2*2**K policies
after eliminating each history's analytically optimized terminal class/abstention.
The K=2 adversarial suite enumerates every policy across priors/costs/risk profiles;
the saved semantic evidence is also checked by a separately implemented recursion.

This is a finite belief-state controlled BSDE special case with endogenous action
selection, not a continuous Brownian fully coupled Y/Z diffusion model. The
previous nonlinear coupled numerical study remains separate. Solving this fitted
law exactly does not establish that its beliefs or optimal actions generalize.

## Strong controls, costs and original-file auditing

Nine arms: initial_only, full_only, all_views, best_fixed (selected on its own
selection split), confidence, myopic one-step value of information, ndu_bsde,
compiled_same_model, and risk_ndu. All use the same fitted law and terminal
rule. The compiled control binds its table to the same kernel and objective;
all its realized actions/reads must equal the online neutral BSDE's. There is no
special BSDE accuracy advantage over the same mathematical dynamic program.

The held-out validation split is not used to tune thresholds or add a winning
policy. Count all acquisition attempts and all actual classification calls.
Measured physical CPU is separate from .02/.04 modeled utility charges. Common
preparation jobs are reported once, alongside each arm's actual validation/test
CPU, plus unallocated work inside a measured envelope. Startup/imports, final
report/audit writing, energy, native journalling/migration and deployment latency
are not fully qualified. Full per-arm lifecycle allocation is false; no unseen
future uses amortize preparation.

The arithmetic audit imports neither a neural model nor the policy/solver. It
reconstructs conditional laws and neutral/risk policies from the stored original
masses, checks information-prefix decisions and each requested view against its
source, then recomputes decoded correctness, coverage, score and CPU sums. The
in-memory private callback is not an authority boundary. Byte hashes and a
successful audit do not authenticate physical execution or source independence.

## Execution and interpretation

Initial local execution used ONLY the declared lexical reference on the original
publisher texts, not an invented mmBERT execution. On 240 test rows, full_only /
selection-chosen best_fixed answer 225, with 218 correct and mean score .8391667.
Neutral ndu_bsde / compiled_same_model answer 193, with 189 correct and mean score
.7228333; myopic scores .7505. The exact fitted-model optimum is NOT the best
observed policy. This negative result is retained, and test labels do not retune
the law or switch thresholds. Low-support conditional modeling, symbol compression
and acquisition cost sensitivity need separate new-data investigation.

The source subtree passed 244 model-free and 41 actual Torch tests without skips,
including all inherited suites. Seven new actual tensor tests use explicitly
synthetic publisher fixtures while executing real encoding/training/control code;
those are NOT physical pretrained evidence. Parent run 38149835808 has succeeded,
including a fresh V3 Encoder; its 8-parameter composition result remains 192/192
with the same exact-control limitation. Parent success cannot qualify this new
source or the new physical acquisition job.

Use the SAME study entrypoint:

```sh
PYTHONPATH=qualification/neuron-stem python3 qualification/neuron-stem/fbsde_study.py \
  --profile semantic_acquisition_v1 --backend hashing_reference_v1 \
  --publisher-root /original/pinned-publisher --output /new/lexical-acquisition
PYTHONPATH=qualification/neuron-stem python3 qualification/neuron-stem/fbsde_study.py \
  --profile semantic_acquisition_v1 --backend mmbert \
  --model-dir /private/model-cache --output /new/physical-acquisition
```

The existing workflow adds separate lexical and real-mmBERT jobs, retaining every
old experiment. Observe exact-source job outcomes before claiming physical model
execution. Both are research profiles: no real production no-change, independent
future efficacy, public-OS trust separation, general FBSDE superiority, native
recovery or production release is claimed. Keep the PR Draft.

Theory context: Cohen and Elliott, *Backward Stochastic Difference Equations and
Nearly Time-Consistent Nonlinear Expectations*, SIAM J. Control Optim.,
DOI 10.1137/090763688. This contextual reference is not substituted for the finite
algebra above. Dataset: Larson et al., EMNLP 2019, D19-1131; immutable source and
license bytes follow the existing DATA_PINS, not a newly assumed license.
