# Fixed-coefficient regenerative diffusion reference

`regenerative_reference.py` supplies an independent FP64 half-line reference for
`dX = drift*dt + sigma*dW`, absorption at zero, a fixed positive refractory delay,
and return to a fixed positive reset distance. It uses SciPy special functions;
it does not import Torch. It complements the exponential-clock
`fixed_delay_reference.py` and the finite-generator `finite_control.py`.

For first-passage CDF `F_x(t)` and event time `T_n`, strong Markov renewal gives
`P(T_n<=T) = F_{x+(n-1)*reset}(T-(n-1)*refractory)`. Summing these tails gives the
mean count; weighting them by `2*n-1` gives its second moment. Their derivatives
give the continuous expected event rate. An initial point at zero contributes
an explicit event atom at time zero, including when the horizon is zero. Positive
drift retains its missing first-passage mass; it is never conditionally normalized.

`discounted_hit` uses an exponentially tilted first-passage distribution.
`value` includes constant active reward, an instantaneous NET event payoff, zero
reward while waiting, and the discounted continuation from reset. Its fixed-policy
boundary value is `event_payoff + exp(-discount*refractory)*value(reset)`.
This implements a regenerative continuation, not a financial terminal equity value
or an optimal free boundary. It does not propagate an arbitrary current density.

All parameters and clocks have explicit finite domains. `max_terms` bounds work
before finite sums; `max_horizon` bounds individual queries. Scalar first-hit
queries do not consume a multi-event budget. The schedule uses exact rational
arithmetic for the supplied FP64 clocks, while probabilities remain FP64 special
function evaluations. CDF addition roundoff up to eight ulps at one is capped;
larger range errors fail. Underflow remains possible. No claim of correctly
rounded output, moving-boundary closed form, coupled-network closed form, training
speedup, historical gate closure or production adoption follows from this reference.

Run the independent density-integral, two-event convolution, moment, atom,
renewal-value and budget checks with:

```sh
python -m unittest qualification.hcsn_adaptive.regenerative_reference_tests -v
```
