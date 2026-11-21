# N256 pre-exponential provider compatibility review

Status: **INPUT STRUCTURE BOUND / PROVIDER EXECUTION HOLD / all_closed=false**.

This read-only stage consumes the two immutable artifact ZIPs preserved by
Draft #6908.  It verifies their identities and duplicate-key RED, then parses
the already-published current-source pre-exponential matrices and seeds with
the Python standard library only.  It executes no propagation, exponential,
provider, model, Torch, optimizer, or training call.

Both authentic augmented matrices are finite Metzler matrices, but both have
positive row sums.  Their exact uniformized transitions therefore have induced
row-vector L1 norm above one.  Four of the five input channels are signed.  The
existing substochastic `SparseSubgenerator` interface is consequently not an
admissible direct provider path for these bytes; an authentic path must use the
separately developed signed, non-substochastic interval construction and must
still supply its missing full-N256 tail, rounding, resource, admission, and
external-review originals.

This closes only the structural routing question for the current frozen input
bytes.  It does not execute or admit the interval provider, establish unique
binary64 rounding for any authentic output, repair #6901, or qualify N256,
later cycles, N512, migration, full-network training, C2 replay, HPCA custody,
production, or adoption.  #6908 remains `RED_DUPLICATE_KEY`; #6901's numerical
cause remains `UNKNOWN`.
