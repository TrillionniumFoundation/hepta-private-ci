# Authentic N256 signed-provider canonical adapter correction

Status: **CANONICAL INPUT FIXED / PROPAGATION HOLD / all_closed=false**.

The immutable #6913 parent emitted Python `float.hex()` text.  The target
signed provider accepts only canonical 16-digit lowercase IEEE-754 binary64
bit strings, so that historical adapter is `RED_NONCANONICAL_INPUT` even
though its private encode/decode loop was byte exact.  This follow-up retains
that failure and changes only the adapter encoding to canonical bit strings.

This stage consumes the two immutable duplicate-run artifacts preserved by
#6908 and the structural routing result in #6910.  It converts both authentic
dense augmented matrices into strictly ordered sparse canonical-bit rows and
all five authentic seed channels into canonical-bit vectors.  Every emitted
coordinate is accepted by the target exact input parser.  It then reconstructs
the original binary64 arrays and requires byte-for-byte equality, including
signed zero in the seed arrays.

The adapter performs no propagation, uniformization series, matrix
exponential, signed interval provider, model, Torch, optimizer, or training
call.  Its output establishes only that the published authentic bytes can be
represented without loss by the existing signed/non-substochastic provider
input schema.  No claim from the incompatible #6913 adapter is transferred.

Provider admission remains blocked on a separately frozen full-N256 execution
contract, growing-tail resource bound, unique-rounding result, independent raw
review, and valid host allocation.  This review does not repair #6901 or
qualify N256, N512, full state, later cycles, migration, full-network training,
C2 replay, HPCA custody, production, or adoption.  #6908 remains
`RED_DUPLICATE_KEY`; #6901's numerical cause remains `UNKNOWN`.
