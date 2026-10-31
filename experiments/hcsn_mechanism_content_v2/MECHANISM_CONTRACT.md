# Renewal content mechanism: mathematical and experimental contract

This experiment tests whether an explicitly propagated event-count distribution changes content predictions and sensing decisions under shared information. It is a controlled mechanism assay. It is not a natural audio/video benchmark, a complete reconstruction of He and Xiong's debt/equity model, or a proof that an entire neural network has a closed-form solution.

The original motivation is [He and Xiong, *Rollover Risk and Credit Risk*, Journal of Finance 67 (2012), 391–430](https://www.princeton.edu/~wxiong/papers/rollover.pdf). That paper's stationary financial model, equity valuation, and endogenous default boundary are distinct from the simpler process defined below. Here the log-gap boundary is fixed at zero. The experiment does **not** solve or train a task-optimal free boundary and does not jointly train the physical diffusion parameters.

## 1. Active state, event, reset, and refractory state

During an active period,

\[
X_t=x+\nu t+\sigma W_t,\qquad x>0,\quad \sigma>0.
\]

An event occurs at the first hitting time of zero. After each event, the process is held at the reset gap \(r>0\) for a deterministic refractory duration \(d>0\). It then starts a new active period from \(r\), with the same \(\nu,\sigma\). Active periods use independent Brownian increments. This is a renewal model with constant coefficients and constant reset/refractory parameters within an episode.

The exact-event simulator restricts \(\nu<0\), so every active first passage is almost surely finite. The CDF itself also supports other finite drifts, but the simulator and reported benchmark do not claim that larger scope.

An observation during a refractory period contains the reset gap and the actual remaining refractory duration. The kernel rejects a positive refractory duration paired with an inconsistent active gap. Removing future refractory intervals in an ablation preserves any already-observed remaining refractory interval.

## 2. Single first passage

For \(t>0\), the lower first-passage CDF is

\[
F(t;x)=\Phi\!\left(\frac{-x-\nu t}{\sigma\sqrt t}\right)
+\exp\!\left(-\frac{2\nu x}{\sigma^2}\right)
\Phi\!\left(\frac{-x+\nu t}{\sigma\sqrt t}\right).
\]

Set \(F(t;x)=0\) when \(t\leq0\). The reflection term distinguishes an event at any intermediate time from a terminal state below the boundary. The density is

\[
f(t;x)=\frac{x}{\sigma\sqrt{2\pi t^3}}
\exp\!\left[-\frac{(x+\nu t)^2}{2\sigma^2t}\right].
\]

The analytic evaluator uses stable normal-CDF expressions. An independent numerical reference integrates this density adaptively without evaluating the analytic CDF. Its work counter records density-integrand evaluations, not neural updates or simulation time steps. A separate event simulator draws inverse-Gaussian passage times with mean \(x/(-\nu)\) and shape \(x^2/\sigma^2\); it calls neither CDF implementation.

## 3. Repeated-event law

Let \(T_n\) be the time of the \(n\)-th event and \(N_T\) the number of events by \(T\). By the strong Markov property, successive active passage times are independent. The passage-time Laplace transform for distance \(x\) is

\[
\mathbb E[e^{-s\tau_x}]
=\exp\!\left[-\frac{x}{\sigma^2}
\left(\nu+\sqrt{\nu^2+2s\sigma^2}\right)\right].
\]

Multiplying transforms shows that the sum of active passage times across distances \(x,r,\ldots,r\) has the same law as one active passage across distance \(x+(n-1)r\). Adding the deterministic inactive time gives

\[
\Pr(T_n\leq T)=F\bigl(T-(n-1)d;\;x+(n-1)r\bigr).
\]

Write this tail as \(A_n(T)\), and set \(A_0(T)=1\). Then

\[
\Pr(N_T=n)=A_n(T)-A_{n+1}(T).
\]

An initially observed remaining refractory time is subtracted from the first available horizon. Positive \(d\) bounds the count support at any finite horizon. The implementation checks its support cap; it does not silently put overflow probability into the last class. When the zero-future-refractory ablation has an infinite possible support, the omitted tail and any permitted numerical normalization correction are explicitly recorded.

## 4. Content propagation

Content is a categorical distribution \(z\). One event applies a specified column-stochastic matrix \(M\). The independent label generator samples the corresponding categorical transition at every actual event. Therefore

\[
z_T=\sum_{n\geq0}\Pr(N_T=n)M^nz_0.
\]

This directly changes the content distribution used for output scoring. It is not an auxiliary feature whose effect on the task is assumed. The equality relies on the stated linear Markov content transition; replacing it by an arbitrary nonlinear neural map of a mean state would not preserve this result.

If a common observation supplies a finite posterior mixture \(\sum_jw_j\delta_{x_j}\), the event probabilities are mixed with those same weights. The ordinary gated and numerical references receive every mixture component and weight as well. The equal-first-two-moments witness only demonstrates that those two moments are not sufficient for this specified first-passage prediction. It does not imply that a general neural vector state cannot encode a distribution.

## 5. Why the bridge observations represent the same process

The simulator first draws a true passage time \(T\). Its observations before that event must form one coherent path; independently redrawing marginal observations at each READ would violate the model.

Let \(K_\nu(t;x,y)\) be the killed Brownian transition density on the positive half-line. Conditional on first passage at \(T\), the density at an intermediate time \(s\) is proportional to

\[
K_\nu(s;x,y)f_\nu(T-s;y)/f_\nu(T;x).
\]

In this ratio, the exponential drift factors cancel. The resulting zero-drift first-passage bridge is the three-dimensional Bessel bridge from \(x\) to zero. It can be sampled as the norm of a three-dimensional Brownian bridge starting from \((x,0,0)\) and ending at zero.

Conditioned on its previous bridge vector \(B_t\), the next vector at \(t+\Delta<T\) is sampled jointly as

\[
B_{t+\Delta}=
\frac{T-t-\Delta}{T-t}B_t
+\sigma\sqrt{\frac{\Delta(T-t-\Delta)}{T-t}}Z,
\qquad Z\sim N(0,I_3).
\]

All arms index the same pre-generated observation grid. READ reveals a value already present on that path; it does not modify the path, reset it, or resample it. Development checks compare the simulator's survivor probability and survivor conditional mean against the killed-density reference.

## 6. What an agent may observe

Before its first READ, the content class is hidden and represented by the common uniform prior. A READ requested at one tick returns at the next tick. It reveals the current content class, current physical gap, and remaining refractory time. READ is a perfect synthetic sensor in this mechanism assay; no claim about natural-signal encoder quality follows from it.

All arms receive the same estimated drift and volatility, obtained from the same independent calibration sufficient statistics, and the same public reset/refractory configuration. They do not receive the true hidden physical parameters. During the mismatch condition, the true episode-constant refractory duration differs from the shared nominal duration. A READ can reveal the remaining duration of the current refractory episode, but does not reveal the hidden global duration automatically.

The policy function accepts observations and estimates, not the actual world trajectory. Its model-generated futures use a separate random-number namespace. These sampled futures are common between paired cores when their visible state and decision time agree, while remaining independent of the actual-world random stream.

## 7. Actions, outputs, and controls

- READ consumes one unit of a fixed budget and incurs a specified fee.
- WAIT advances the common external clock without observing content.
- STOP disables further sensing and control. It does not remove any mandatory output or its propagation cost.

There are four mandatory output times. The principal matrix compares ordinary versus analytic propagation under a lightweight controller and a task-value controller. The latter plans one next READ using a calibrated model, replans over time, and accounts for future required outputs. It is a receding heuristic, not a globally optimal QVI solver.

The ordinary baseline is a 23,712-parameter feed-forward gated residual propagator, not an SSM. It is trained on independent sampled event counts. Both cores enforce the common deterministic support constraint. The analytic core has no trainable core parameters and uses the specified process law plus the common calibration. The unequal parameter counts and the analytic structural prior are reported explicitly.

Three interventions supplement the matrix: forecast-risk suppression in the policy only, ordinary propagation on the analytic lightweight action schedule, and held-last-content prediction on that same schedule. Raw action and content divergences are reported separately. Forecast suppression is not a proof that an independent financial Put channel is necessary.

## 8. Scoring, uncertainty, and cost

Accuracy, negative log likelihood, and Brier score are recomputed from raw output probabilities and actual content labels. The reported numerical NLL floors a predicted label probability at `1e-12`; it is therefore a clipped score when an ablation assigns zero probability to an observed outcome. The analyzer also records zero-probability label frequencies. READ counts come from raw access records. Task utility is accuracy minus the fixed READ tariff; it does not monetize CPU time or measure joules.

Primary and secondary arm differences use paired episodes. The descriptive bootstrap resamples the three fitted-seed groups and then paired episodes within each selected group. Model-matched and hidden-refractory-mismatch results are separate. With only three fitted seeds, interval exclusion is evidence about this experiment, not broad architecture superiority.

Complete worker receipts include fresh-interpreter startup, loading, training, evaluation, and evidence serialization. Each fitted ordinary checkpoint is charged once per training seed, rather than once per arm, condition, or repeated embedded training report. Controller and core internal timers overlap and are never summed. Per-worker peak RSS is not a measurement of concurrent aggregate memory. Sensor/network latency and energy are not physically measured by this synthetic experiment.

The propagation formula is exact only under its declared local model and parameters. Calibration error, hidden refractory mismatch, nonlinear content dynamics, changing coefficients, learned boundaries, coupling across neurons, and whole-network training lie outside that exactness claim.
