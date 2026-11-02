# Continuous first-passage/reset numerical reference

This line extends the interval-censored process archived at commit
`012bcf3505cb9306d9cef094a1acc3ca34c978be`. The old trained models and old
confirmation results remain intact. This reference is not their exact numerical
replacement and is not connected to their learned controller or native owner.

The new reference implements `dX = drift dt + diffusion dW` inside
`(-boundary, boundary)`. It first samples whether any boundary is reached within
the remaining interval using the competing two-boundary exit CDF. On a hit it
numerically inverts that CDF, samples the side from its boundary probability
fluxes at the resolved time, starts an exponential refractory clock at that
actual hit time, and consumes the interval's remaining duration. If recovery
finishes before the interval ends, it samples a reset voltage and continues.
On no hit, it samples the endpoint from the killed transition law conditioned
on survival. Thus excursions that cross a boundary and return before the
external tick are included, and an external interval may contain many events.

For an active starting point `x`, write `u=x+b`, `L=2b` and `a_k=u+2kL`.
The lower-boundary probability flux is

\[
f_-(t)=\frac{\exp(-\mu u/\sigma^2-\mu^2t/(2\sigma^2))}
 {\sigma\sqrt{2\pi t^3}}
 \sum_k a_k\exp\{-a_k^2/(2\sigma^2t)\}.
\]

Reflection gives the upper-boundary flux. Time-integrated image terms give the
competing CDF; integrating the killed image density over voltage gives its
unconditional surviving endpoint CDF. The implementation checks exit plus
survival mass without silently normalizing a defective row. These analytic laws
are evaluated through finite image sums and numerical root finding.

`Law` uses the baseline's bounded Brownian physical envelope: boundary [.8,1.2],
diffusion [.35,.8], |drift|≤1.1, recovery rate [.25,2], reset centers within .6b,
and individual advance durations [0,2]. Drift is constant during each call.
`reset_sd=0` specifies point resets; positive `reset_sd≤.12b` specifies a
continuous Gaussian conditioned to remain strictly between the two boundaries.
This is explicitly different from the archived finite folded-Gaussian-bin reset.
No crossing at a reset is silently suppressed: the declared reset law has no
boundary/outside atom.

The returned event record contains resolved local hit time, side, sampled
refractory duration, and release time (which can lie after the current interval).
The checkpoint stores mode, actual residual refractory duration, voltage and
PCG64 state. Resume reproduces subsequent state and event records exactly under
the same implementation. A duration-zero call is an identity. `advance` does not
commit either state or RNG on an event-guard failure; it raises instead of
silently dropping subsequent events or residual time.

Numerical qualification is bounded. Image sums use 12 terms on each side;
inversion has absolute tolerance 2e-11 and relative tolerance 1e-13. These are
algorithm settings, not a proven universal error bound. Very small unresolved
hitting times, invalid mass/flux, invalid states or envelopes, and an event count
beyond the explicit guard are errors. The implementation is not mathematical
exact simulation, is not differentiated through the numerical inversion, and
has no claimed full-parameter training gradient, Rust parity, energy advantage,
learned task benefit, free-boundary or production qualification.

Run:

```bash
python3 tools/hcsn/digital_read_followup_20261101/continuous_renewal_validate.py --samples 4000
```

The validation reference is independent central finite differences and a
continuous-time Markov generator, with its own mesh bias measured at two
resolutions. It does not call the image kernel. The checks include mass,
reflection, time derivative versus probability flux, killed-law PDE comparison,
regenerative state/count comparison, a whole-interval versus two-part
Markov-law comparison, exact checkpoint replay, residual recovery semantics,
and explicit overflow rejection. Monte Carlo acceptance uses six empirical
standard errors plus measured mesh difference and a declared small numerical
allowance; it is a diagnostic acceptance band, not a familywise confidence
statement or a proof of a continuous semigroup.
