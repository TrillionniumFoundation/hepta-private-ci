# Completed baseline36 and C1: clock-sampling supplement v2

This new, separately identified supplement retains the v1 failed review and its
22.93758828798309 seconds of whole-process wall and 21.723336 seconds of waited
child CPU. The old overall failure, seven C1 errors, source files, full output
archive and execution receipt remain unchanged. The original36 passed subrecords
and six representative fresh-forward artifacts may be reused only after all their
recorded input/source SHA256 values have been rechecked. No original training or
baseline forward is repeated.

The pinned C1 source samples `elapsed()` twice when constructing each epoch row:
the phase clock is sampled first; the cumulative clock adds the complete original
parent outer wall to a second, later sample. The old frozen logical helper expected
these two samples to be identical within one microsecond. The actual retained
attention seed101/LR0.001 source and raw rows demonstrate positive gaps of about
1.5–3.7 microseconds. The failed v1 evidence is not overwritten.

The new adapter checks the exact source AST and, for every actual continued row,
requires finite values and the strict inequalities

`0 <= raw_phase_early <= raw_cumulative - complete_parent_outer <= complete_child_outer`.

There is no widened tolerance. Negative gaps, nonfinite values, or a late sample
beyond the outer process end fail closed. The unchanged frozen logical helper
receives a deep copy whose phase observation clock is the derived late sample.
Every original raw row, journal byte, cumulative time, quality cut, first observed
crossing and cost remains unchanged. Both interval endpoints and their difference
are preserved in the output. The adapter is tested with the complete actual 23-row
positive-gap example and explicit negative-gap/out-of-bounds/nonfinite rejection.

All seven actual C1 chains are audited again, including hashes, exact parent outer
records, source equivalence, model configuration, journal/update counts, optimizer
state, plateau/strict-best history, inherited memorization, sample-order recurrence
and final RNG endpoints. The seven selected C1 checkpoints are freshly evaluated
on all development episodes with the exact original-v8 model, batch32, no gradients
and one CPU thread. No resume-start snapshot exists, so this does not directly
observe the first resumed optimizer state. No optimizer step is executed.

This is only the already completed baseline36 plus seven C1 chains. The six HCSN
candidate directories are excluded, and this is not final42 verification or
scientific admission. The frozen reviewer v2 remains byte-identical to its
`039dc18d0cec08135a6ba3108fe25b4493eaca61e0d0340081895ec93a97fbaf` capsule.

The descriptive per-core table selects one common LR by mean D macro-F1 across
all three declared seeds. Both LR rosters and all six original processes plus C1
are charged. All original memorization failures remain failures. D is tuning data,
not independent confirmation. If any C1 audit fails, the completed core table is
withheld; costs still include every declared completed phase.

New validation and actual-review costs are separate from the prior failed review.
Summed process walls are not calendar wall. C1 controller waited-child CPU includes
preflight, and report CPU samples precede serialization; exact per-fit exit CPU and
energy remain unknown. UTC intervals record possible overlap with live HCSN workers.

Run once in a new directory:

```
python -B run_c1_clock_supplement.py \
  --base /home/qian-qi/hepta-hcsn-core-study-20261110-c385-training \
  --output /home/qian-qi/hepta-hcsn-independent-baseline36-c1-20261110-c385-v2
```
