# Independent uniformization primitive — source stage only

This package implements one bounded method primitive that Draft #6316 left
missing: a standard-library-only Decimal row-vector action for finite sparse
Metzler matrices. It does not import NumPy, SciPy, the N256 candidate, or the
existing oracle.

For a rate `lambda` no smaller than every negative diagonal magnitude, the
implementation forms `P = I + A / lambda` and evaluates

`v exp(A t) = exp(-lambda t) sum_k ((lambda t)^k / k!) v P^k`.

The emitted L1 upper bound covers the omitted positive series using the induced
row-vector L1 norm, including nonconservative augmented selector matrices where
the transition norm exceeds one. Decimal input conversion and finite-precision
rounding are explicitly **not** certified by this stage.

Small fixtures cover a closed-form absorbing chain, signed input, zero duration,
a nonconservative augmented selector, rejected non-Metzler input, bounded-work
failure, and source independence. Normal and optimized-mode fixtures pass.

The first local development run is retained as 4/5 with one failed test oracle:
the expected absorbed mass was subtracted after leaving its 80-digit Decimal
context. Moving that expected-value subtraction inside the same context fixed
only the test oracle; the primitive source was unchanged. The subsequent normal
and optimized runs are 5/5.

This is not the full N256 provider. It has no authentic-input loader, packet
engine, delay/reset/nonreturning-upper reconstruction, full-roster stiffness or
cost bound, independent review, input/rounding certificate, resource admission,
provider admission, or numerical key. It executes zero N256 work and grants no
large-grid, checkpoint, training, production, or global qualification.

Global status remains `HOLD / all_closed=false`.
