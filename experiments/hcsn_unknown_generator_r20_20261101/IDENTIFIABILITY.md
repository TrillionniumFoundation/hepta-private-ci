# One-READ observation limit

The bounded protocol contains the following four lawful owner streams. Their first four WRITEs initialize addresses 0,1,2,3 with value 0. The next two WRITEs are erased. Eight shared distractors follow, and the query addresses 0. Every public raw token, mask, alias bridge and query can therefore be identical.

| Owner world | Missing WRITE at position 4 | Missing WRITE at position 5 | Query target |
| --- | --- | --- | --- |
| W0 | address0,value0 | address1,value0 | 0 |
| W1 | address0,value1 | address1,value0 | 1 |
| W2 | address1,value0 | address0,value0 | 0 |
| W3 | address1,value0 | address0,value1 | 1 |

A deterministic policy chooses the same first action on the common public prefix. If it buys position4, W2/W3 produce the same acquired receipt and different targets. If it buys position5, W0/W1 do so. With no READ, the original ambiguity remains. A single acquired nonquery WRITE does not identify the unread query WRITE. The schedule and key constraints do not resolve this pair: both placements have six WRITEs, the required initial key permutation and two distinct final keys.

Under the explicit uniform distribution on these four worlds, any one-READ policy, including randomized index choices, leaves an unresolved target with probability one-half. Its conditional best accuracy on that unresolved branch is one-half; answering every world attains at most three-quarters accuracy. A selection rule may abstain on ambiguous branches, but that does not create nontrivial reliable fractional-answer coverage. Correct identifiability refusal and a failed uncertain-coverage gate must remain distinct conclusions.

This is a finite observation counterexample, not a statement that every declared population is unlearnable. Law assumptions, additional observations or different tasks can permit calibrated uncertain answers. Finite calibration provides evidence only under its stated sampling/transport assumptions. It cannot guarantee 90% correct fractional answers over all arbitrary unseen laws consistent with the same observable transcript. `ambiguity.py` constructs the actual raw streams and verifies both identical-receipt/different-target pairs; `IDENTIFIABILITY_LIMIT.json` retains its output.

The R20 selection gate therefore retains its original 10% risk target and at least32 fractional accepted answers on each confirmation panel. An all-abstain or point-mass-only fallback remains a failed uncertainty qualification. The label-transport panel tests an explicitly declared permutation assumption; the lag-two +2 panel tests a separate, untrained structural change.
