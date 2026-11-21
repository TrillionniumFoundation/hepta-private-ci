# Signed exact streaming small-fixture candidate

Status: **SMALL SYNTHETIC ONLY / RESOURCE HOLD / all_closed=false**.

This separately frozen candidate addresses one internal peak-liveness property
of #6918.  It parses the operator and duration once, copies every vector's
binary64 strings, and fully validates every vector before returning an
iterator.  It then parses, evaluates, and yields one vector at a time.  A bad
later vector therefore cannot produce partial numerical output, while caller
mutation after admission cannot change the frozen request.

On the same bounded two-state, five-vector fixture, every streamed output bit
and complete exact certificate equals both five scalar calls and the #6918
batch result.  Normal and optimized-mode tests cover mutation, malformed-later
input, the 16-vector cap, and the source structure.

For the authentic input sizes already frozen by #6920, double parsing of the
vectors would raise input conversions from 4,379 for #6918 to 6,964, still
4,591 below the ten-scalar total of 11,555.  The candidate reduces its own
parsed-vector liveness from five vectors to one, but this is not an RSS or
wall-time measurement.  It does not reduce the ten independent recurrences or
their 9,195,520 maximum sparse-contribution and 2,517,790 interval-rounding
bounds.

This stage loads no authentic N256 bundle and performs no authentic provider,
dynamic, expm, Torch, optimizer, training, HPCA, production, or adoption work.
It does not close resource allocation, N256/N512/full-state, migration,
full-network, C2 replay, or HPCA custody gates.

#6908 remains `RED_DUPLICATE_KEY`; #6913 remains
`RED_NONCANONICAL_INPUT`; #6901's numerical cause remains `UNKNOWN`; C2 full
replay remains 0/6; HPCA remains NoUpdate; `all_closed=false`.
