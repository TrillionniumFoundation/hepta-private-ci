# Signed exact recurrence cursor small-fixture control

Status: **SMALL SYNTHETIC ONLY / RESOURCE HOLD / all_closed=false**.

This separately frozen stage makes the exact signed uniformization recurrence
interruptible on a bounded fixture.  It snapshots and validates one request,
advances by a caller-bounded number of tail checks, and encodes every exact
recurrence variable in canonical JSON.  A fresh loader revalidates the frozen
request before continuing.

For both positive/negative signed two-state vectors, uninterrupted execution
and a save/decode after every unsuccessful tail check equal the existing scalar
provider bit-for-bit, including the complete exact certificate.  Each path
needs 20 saved continuations before unique rounding at included index 20.  The
largest encoded cursor is 677 bytes.  Zero-duration snapshot behavior is also
identical to the scalar provider.

The envelope's canonical SHA-256 detects accidental byte/body corruption.  It
is not a signature, external custody, or proof that a hostile writer did not
replace both body and digest.  The loader is a small-fixture cold-continuation
control, not an authentic checkpoint authority.

Hard bounds are 32 states, 1,024 terms, and 131,072 encoded bytes.  This stage
loads no authentic N256 bundle and performs no authentic provider, dynamic,
matrix-exponential, serializer, Torch, optimizer, training, HPCA, production,
or adoption work.  It does not close N256 resource admission, authentic
full-state/cold-restart, arbitrary histories, third or later cycles, N512,
migration, full-network, C2 full replay, or HPCA custody/benefit gates.

#6908 remains `RED_DUPLICATE_KEY`; #6913 remains
`RED_NONCANONICAL_INPUT`; #6901's numerical cause remains `UNKNOWN`; C2 full
replay remains 0/6; HPCA remains NoUpdate; `all_closed=false`.
