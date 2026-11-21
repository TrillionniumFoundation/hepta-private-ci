# Authentic N256 signed-provider adapter review

Status: **BYTE-EXACT ADAPTER CLOSED / PROPAGATION HOLD / all_closed=false**.

This stage consumes the two immutable duplicate-run artifacts preserved by
#6908 and the structural routing result in #6910.  It converts both authentic
dense augmented matrices into strictly ordered sparse hexadecimal rows and all
five authentic seed channels into hexadecimal vectors.  It then reconstructs
the original binary64 arrays and requires byte-for-byte equality, including
signed zero in the seed arrays.

The adapter performs no propagation, uniformization series, matrix
exponential, signed interval provider, model, Torch, optimizer, or training
call.  Its output establishes only that the published authentic bytes can be
represented without loss by the existing signed/non-substochastic provider
input schema.

Provider admission remains blocked on a separately frozen full-N256 execution
contract, growing-tail resource bound, unique-rounding result, independent raw
review, and valid host allocation.  This review does not repair #6901 or
qualify N256, N512, full state, later cycles, migration, full-network training,
C2 replay, HPCA custody, production, or adoption.  #6908 remains
`RED_DUPLICATE_KEY`; #6901's numerical cause remains `UNKNOWN`.
