# Typed FPT adoption, credit and publication contract

## Coordinate and clock conventions

`checkpoint.level` is a distance coordinate `X` with a **lower** barrier `b`;
the active domain is `X > b`. An upper membrane threshold is mapped by

\[
X=b+(V_{th}-V),\qquad \mu_X=-\mu_V,\qquad
\sigma_X=\sigma_V,\qquad X_{reset}=b+\text{reset_gap}.
\]

Replacing `W` by `-W` preserves Brownian law. Consequently the negative drift in
the fixture moves distance toward its lower barrier; it is not a sign error in
the upper-barrier one-touch formula. `drift` and `weights` describe the distance
process. Drift is distance/second, volatility is distance/sqrt(second), and
`cancel_rate` is inverse seconds. Physical timestamps and refractory intervals
are integer microseconds; the separate owner monotonic clock orders native ticks.

At genesis, time, event count and diffusion draw counter are zero and phase is
Active. A reported hit resets the level to `b + reset_gap` and holds it until
`hit + refractory_us`. During holding, the diffusion draw counter cannot advance.
At the release instant the reset level is preserved. With positive reset gap,
an ensuing hit requires positive active time: under this integer protocol its
timestamp must be **at least release + 1 microsecond**. Producers must not round
a positive first-passage time down onto release. This is a quantization contract,
not a proof that any unobserved continuous-time path was generated correctly.

Event timestamps increase strictly, match the increment in total events, obey
every intervening refractory interval, and precede the cancellation instant.
At a cancellation tie the task is cancelled; a hit at the same time is invalid.
Cancellation is checked even inside refractory holding. The cancellation sample
is drawn once by the producer (`counter=1` when rate is positive; no sample and
`counter=0` at zero rate) and remains fixed through resets and holding intervals.

All numeric model parameters, feature dimensions, objective/artifact identities,
budget, deadline and price rule are fixed per run. Learning can produce a new
identified configuration for a new run; it cannot mutate an admitted one.
Unknown fields, nonfinite values, out-of-domain scalars, inconsistent phase,
regressing time/counters, stale predecessor and stale credit are rejected.

## Resource price: decay, admit, charge

Let `p` be integer price micro-units and `r` its persisted fractional numerator.
With `S = 4,000,000`, the exact represented price in micro-units is
`p + r/S`, where `0 <= r < S`. Let `q = target_quarters`, so the target rate is
`q/4` read attempts per physical second. Let `eta = step_micros`, `M` be the
maximum price, `dt` the elapsed physical microseconds and `c` the observed
attempt count, either zero or one. Using scaled integer state `z = S*p + r`:

\[
z_{admit}=\max(0,z-\eta q\,dt),\qquad
z_{next}=\min(SM,z_{admit}+\eta S c).
\]

The read is eligible on price only if `z_admit <= S*maximum_read_price_micros`.
Both the floor and the fractional residue participate in this comparison.
Prior, admission and resulting pairs are in the same settlement record as the
native anchor and observation. `expected_price_*` binds the prior settled pair,
while admission price is derived from that pair and the request's physical time.
An opened read that fails, including invalid UTF-8, is charged once. A source
rejected before opening has no read attempt. Native abstention, cancellation,
deadline, STOP, WAIT, hard budget and price guards incur no read attempt.

These equations deliberately apply two projections in event order. Projecting
only after the combined term `eta*(c-rate*dt)` would allow idle time at zero
price to prepay a later read. Applying the gate to the previous price would also
make an explicit WAIT change read admission at an otherwise identical endpoint.
Both counterexamples were reproduced on the preceding binary and are retained.

For idle evolution `D_t(z)=max(0,z-eta*q*t)`,
`D_s(D_t(z))=D_(s+t)(z)`. The integer residue makes this identity exact, including
sub-micro-unit changes; zero-time WAIT is the identity. Endpoint charging is
`C_c(z)=min(SM,z+eta*S*c)`, so inserting an explicit WAIT at the same endpoint
does not change `C_c(D_t(z))` or its admission test. This is the tested scope of
time-partition invariance; it does not equate actions occurring at different
physical times. Full calculations use `i128`; within the declared domains the
largest time-decay intermediate is at most `3.456e20`, safely below its range.
Projection ensures `0 <= z <= SM`. Boundedness and these accounting invariants
are not a proof of policy optimality or convergence of the neural model.

The physical timestamp is supplied by a trusted producer. The mechanism does
not authenticate a hardware clock or measure power. Its target unit is attempts
per trusted checkpoint-second, and its price is separate from physical killing
rate lambda.

## State ownership and commit order

An OS lock file is held by one process throughout the transaction. Regular files
are opened with Linux `O_NOFOLLOW | O_NONBLOCK`; dangling links, FIFOs and other
nonregular sources are rejected. The store directory must be private and ordinary.
Source parent directories and the owner tree must not be renamed or rewritten
concurrently by an untrusted process sharing the same user identity.

1. Read and validate the contiguous settlement chain, full typed request history,
   native-anchor links, budget, price recurrence and outcome semantics.
2. If the next dispatch exists without a settled record, refuse **all** operations
   with `Indeterminate`, including historical replays, before opening native state.
3. Publish the prepared request, then a dispatch fence bound to its request hash.
4. Bootstrap/recover the actual native runtime and tick it once. Its input binds
   the complete adoption request, including model and cancellation identities.
5. Apply the ordered guards and perform at most one bounded local read.
6. Publish a single typed result containing the observation and credit state.

Publication writes a new private temporary file, syncs it, hard-links it to the
final name without replacement, syncs the directory, removes the temporary, and
syncs again. Readers see a complete final file or no file. The actual native
journal and witness remain the sparse-state authority; there is no Python shadow
sparse state. Body hashes are damage checks, not signatures.

The source and record limits are respectively 64 KiB and 128 KiB; the run has at
most 256 transactions. A final settlement is immutable and replay consumes zero
additional attempts. A prepared request with no dispatch is safe to resume.
A dispatch with no final settlement is permanently quarantined in this profile:
the effect may have happened, even if a synced temporary contains a plausible
result. Recovery never infers an outcome from that temporary or retries the read.

## What remains an external integration obligation

Production adoption needs a trusted/attested observation producer, actual model
and NDU artifact selection, authoritative TaskFlow effect identity and admission,
an idempotent or queryable effect adapter for indeterminate cases, and the existing
authenticated Organ Credit mechanism. This executable does not bypass or replace
those owners. Its fixture numeric head and synthetic task files provide executable
engineering evidence; they do not establish task-level utility or production readiness.
