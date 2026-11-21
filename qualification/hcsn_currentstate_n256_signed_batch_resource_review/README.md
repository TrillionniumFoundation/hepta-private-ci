# Authentic N256 signed-batch resource review

Status: **RESOURCE HOLD / 0 AUTHENTIC PROVIDER CALLS / all_closed=false**.

This review applies the shared-parse structure from #6918 to the canonical
authentic N256 inputs without executing the batch provider or its recurrence.
It reads the original artifact once, uses the frozen adapter twice, and checks
the candidate source structurally.

One batch per lane would parse each operator and duration once.  Exact input
conversions fall from 11,555 for ten scalar calls to 4,379 for two five-vector
batches, a reduction of 7,176 (`7176/11555`, or exactly
`143520/2311` percent).  The ten vector recurrences are still independent, so
the previously frozen sparse-action, contribution, and interval-rounding work
does not fall: the maximum remains 9,195,520 sparse contributions and
2,517,790 interval-bound roundings at the 1,024-term limit.

This static reduction is not a peak-RSS or wall-time bound.  No valid host
allocation is available, so authentic execution remains inadmissible.  The
review performs no signed provider call, recurrence, dynamic kernel,
exponential action, Torch operation, optimizer step, training, or production
action.

#6908 remains `RED_DUPLICATE_KEY`; immutable #6913 remains
`RED_NONCANONICAL_INPUT`; #6901's numerical cause remains `UNKNOWN`.  Nothing
here qualifies N256/N512, current/full state, migration, C2 replay, HPCA
custody, production, or adoption.
