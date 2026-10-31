# Theory and training scope of Round6

Round6 implements fitted conditional-law forecasts and supervised repair readouts coupled to the **existing fixed Hepta sparse mechanism**, on a synthetic paid-feedback task with actual text/PNG deliveries and native execution. The code supports an empirical operator/readout comparison. It does not establish a new neuron architecture, end-to-end training of the native sparse core, or universal superiority. Sources: [task law](data.py), [fitting](learning.py), [actual execution](study.py), [original sparse adapter](../native.rs).

## 1. Call and put share one conditional law

**Mathematical derivation for the implemented law.** For

$$
E\mid\mathcal F\sim\sum_{j=1}^{K}w_j\mathcal N(\mu_j,v_j),\qquad K\in\{1,2\},
$$

write

$$
F_{\mathcal F}(k)=\sum_j w_j\Phi\!\left(\frac{k-\mu_j}{\sqrt{v_j}}\right).
$$

With the explicit events `put: E <= k` and `call: E > k`,

$$
p_{\rm put}(k)=F_{\mathcal F}(k),\qquad
p_{\rm call}(k)=1-F_{\mathcal F}(k),\qquad
p_{\rm put}(k)+p_{\rm call}(k)=1.
$$

They are two directional queries of shared weights, means and variances. They need not be independently parameterized neuron species. Numerically evaluating both tails stably remains useful; computing an extreme upper tail by subtracting a rounded CDF from one can lose precision. [Conditional-law and event implementation](../round4/runtime_law.py).

The task uses **two distinct cutoffs**, `l=-sqrt(c)` and `u=sqrt(c)`, where `c` is public repair cost:

$$
(p_{\rm put},p_{\rm neutral},p_{\rm call})=
\bigl(F_{\mathcal F}(l),F_{\mathcal F}(u)-F_{\mathcal F}(l),1-F_{\mathcal F}(u)\bigr).
$$

All three sum to one, while call plus put equals one minus neutral. The same-threshold complement identity must not be applied to the two-cutoff tails. A single Gaussian gives the usual probit form; the `gaussian` and `probit` controls condition that same fitted law through separate precision and dense implementations. These are statistical conditional probabilities, with no option-price discount factor or identification with a market risk-neutral measure. [Law release](../round4/runtime_law.py), [Gaussian controls](../round4/runtime_learning.py), [physical native head](../native_head.rs).

## 2. Three different meanings must stay separate

| Object | Actual Round6 meaning |
| --- | --- |
| Terminal event probability | Probability of a residual interval or tail, given acquired information. The residual is constant within a trajectory. |
| Transmitted `event` increment | Difference between successive **quantized law coordinates**: mixture weights, means and log variances. `direct` sends corresponding absolute coordinates; `float` transports FP64 coordinates. |
| Native sparse activity | Actual activations, thresholds and eligibility traces produced by the original sparse kernel for supplied numeric drives. |

The codec does not sample Bernoulli spikes from call/put probabilities. A zero transmitted increment is not a missing observation, survival probability, first-passage event or physical reset. Event and direct modes are alternative representations of the same decoded quantized state; event coding alone does not create a larger function class. [Codec](../round4/runtime_codec.py), [acquired-state owner](../round4/runtime_owner.py), [task generator](data.py).

For analytic/numeric readouts, each of three channels executes a fresh **two-tick native probe**: a signed drive plus a fixed reference drive, followed by zero drive. The second tick retains the first tick's state. Each probe begins with fresh sparse state; these feature probes do not carry their state between paid-sensor stages. Separately, the typed Owner/native component journals retain and restore their own state across acquired updates. Round6 does not demonstrate arbitrarily long recurrent memory. [Feature construction](../round3/feedback.py), [probe lifecycle and fixed configuration](../native.rs), [typed native runtime](../native_head.rs).

## 3. What is actually trained

| Part | Training or adaptation in this round |
| --- | --- |
| Two-component prior | Mixture weights, means and variances fitted by 80 EM updates on training residuals. |
| Sensor-noise multiplier | Supervised maximum-likelihood estimate from both training sensor errors and their declared variances. |
| One-Gaussian control | Mean and variance estimated from the same training residuals. |
| Input normalization / history basis | Training means/scales and 43 deterministically selected standardized training centers; no gradient fitting of those centers. |
| Analytic, numeric, history readouts | 63 coefficients per readout, fitted to actual supervised repair gains by ridge MSE gradient descent; development chooses the ridge setting and additive score offset. |
| Native sparse core / codec | Configuration, connectivity, decay coefficients, top-k rule, quantization and frame rules remain fixed. State-dependent thresholds and traces evolve under those fixed rules. |

There are three distinct 600-step ridge fits per arm and five offsets per fit: **15 candidate evaluations per arm**, not 15 separately fitted weight trajectories. Across five seeds and three learned arms, this is 45 distinct ridge GD trajectories, 225 weight/offset candidate evaluations and 15 selected readouts. [Dynamics fit](../round4/runtime_learning.py), [readout fit and selection](../round3/feedback.py), [Round6 preparation](learning.py).

Analytic and numeric controls use the same native sparse mechanism and feature budget, with probability-derived versus public numeric drives. History uses 20 polynomial and 43 radial features of the acquired sufficient-statistic summary. No gradient is propagated through the native sparse kernel, codec or action argmax. This is supervised action-value fitting with a shared analytic planning rule; it is not sampled-DQN training. Empirical calibration does not change the native profile's UNQUALIFIED/DENY_ALL posture. [Features](../round3/feedback.py), [action selection](study.py), [native profile](../native_head.rs).

## 4. Limited relationship to *Deep Q-Learning on Hölder Spaces*

The [published PMLR abstract](https://proceedings.mlr.press/v336/qi26a.html) for Qian Qi's paper ([arXiv record](https://arxiv.org/abs/2606.16846)) studies Bellman targets for continuous-state/action stochastic control under uniformly elliptic diffusions and Hölder-regular coefficients. It describes state smoothing, only Lipschitz action dependence, anisotropic neural-operator approximation and resource bounds as the time step shrinks. It explicitly separates this operator analysis from convergence of practical sampled DQN. This summary uses the published abstract; it does not assert an independent verification of every full-paper theorem.

**Our own mathematical connection:** for `h > 0` and `sigma > 0`, under the separate constant-coefficient diffusion model

$$
X_{t+h}=x+bh+\sigma\sqrt h\,Z,
$$

the digital-tail operator is Gaussian smoothing of an indicator:

$$
P(X_{t+h}>k\mid X_t=x)=\Phi\!\left(\frac{x+bh-k}{\sigma\sqrt h}\right),\qquad
\sup_x|\partial_x p|=\frac{1}{\sqrt{2\pi}\,\sigma\sqrt h}.
$$

This elementary derivation illustrates positive-time smoothing and deteriorating derivative scales as noise/time vanish. It is a conceptual connection, not a theorem about the present implementation.

In Round6, `E` does **not** follow that diffusion: observations update a Bayesian belief about a constant latent residual. Actions are stop, repair or one paid observation. The shared continuation is an unconstrained continuous-repair lookahead; it does not model future codec distortion, learned future-readout decisions or finite-domain refusal. [Task law](data.py), [continuation](continuation.py), [precise finite-domain interpretation](evidence/review_interpretation_001/INTERPRETATION.md).

Transferring a Bellman regularity result would require a specified controlled Markov/belief-state process and proof of its coefficient, ellipticity, action, payoff and function-space assumptions. The current two-stage partially observed task and hard selection/quantization do not supply those assumptions. Neither paper-level regularity nor a Gaussian closed form establishes a newly superior spiking architecture or sampled-training convergence.

## Reporting boundary

Supported wording is: **fitted probabilistic operators and supervised readouts, transmitted through event/absolute/FP64 codecs and executed with the original fixed native sparse mechanism**. The confirmation determines the registered empirical utility and calibration outcomes. Native execution or a correct probability formula is not, by itself, an advantage result. Any actual runtime/domain refusal remains a recorded execution failure rather than a discarded confirmation sample.

This document is outside the primary freeze and contains no confirmation result. Its source reading was checked against PREPARED SHA256 `01cd90245b3d024d5be8676a684266c44a2e8e608fd9d175625db979d48d688a`; no primary source, model or prepared artifact was changed.
