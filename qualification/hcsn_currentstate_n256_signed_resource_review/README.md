# Authentic N256 signed-provider resource review

Status: **RESOURCE HOLD / 0 PROVIDER CALLS / all_closed=false**.

This review consumes the canonical authentic adapter from #6916 and statically
audits the existing scalar signed-provider loop.  It freezes the exact call
denominator and the deterministic sparse-action and bound-rounding work before
any provider execution.

The two lanes contain five vectors each, so the current scalar API requires ten
provider calls and reparses each operator five times.  The growing-tail
condition cannot first be checked until index 537.  Reaching that check requires
4,822,260 sparse product contributions across all ten calls; exhausting the
default 1,024-term limit would require 9,195,520.  The default-limit path can
also request up to 2,517,790 exact interval-bound roundings.

These counts are not an RSS or wall-time bound.  No current host peak-memory
bound, wall-time bound, or valid allocation is available, so provider admission
remains false.  This review executes no provider, dynamic kernel, exponential
action, Torch operation, optimizer step, training, or production action.

#6908 remains `RED_DUPLICATE_KEY`; the immutable #6913 adapter remains
`RED_NONCANONICAL_INPUT`; #6901's numerical cause remains `UNKNOWN`.  Nothing
here qualifies N256/N512, current/full state, migration, C2 replay, HPCA
custody, production, or adoption.
