# Preregistered next mechanism: credit verified current-policy actions

This is a concrete A-only corpus and prospective mechanism, not a successful
new fit. The completed 96-call candidate and its NoUpdate result remain unchanged.
No new weights or model calls have been produced for this mechanism.

## Observation and hypothesis

The matched all-actions student recovered two failed A tasks but regressed all
three of its initial A successes. Its original authored trajectories included
partial patches that failed the business criterion, yet those assistant tokens
received positive imitation loss. Training also ended at the final successful
patch, leaving the forced next action after a positive verification untrained.
This motivates testing credit assignment and success preservation using the
updated student's actual A actions and feedback.

The external-source failures separately show incorrect branches, argument counts
and return values, and repeated incorrect assertions after failure feedback.
They are diagnostic evidence about the current limit. No B answer, execution
trace, source snippet, label or correction enters this corpus, and no B observation
will select training hyperparameters or a candidate.

## Fixed material and treatment

The corpus binds the twelve actual A calls from model
`430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786`
in the completed `992f2b3` execution. Each record retains both raw student actions
and their actual feedback. A third, explicitly authored correction chooses the
earliest verified student patch, or the already authorized A reference if neither
attempt passed. All six chosen targets are executed again against the original
strict verifier. That final correction is not relabeled as a new student call or
an independent teacher.

The proposed experiment has a retained NoUpdate parent and two new fits resumed
from the identical parent adapter, with fresh identical optimizer state. Both fits
must execute every identical full-context assistant turn, padded position,
language-model head position and backward graph. The **all-observed** arm
supervises every student action plus the verified correction. The
**verified-credit** arm weights unverified student-action losses by zero, while
supervising verified actions and the correction. Observation tokens remain
masked. The complete information and computed positions stay equal; the loss
weights are the treatment.

Planned fixed settings are rank-4 existing q/v adapters, 64 updates, seed 1729,
AdamW learning rate 0.0001, betas 0.9/0.999, epsilon 1e-8, weight decay 0.01,
gradient clipping 1, and a 2,048-token training limit. Both fits share their exact
parent parameter hash. A prefit encoding overflow or identity mismatch is a
failed candidate, not permission to silently truncate or change the setting.
Optimizer state from the old fit is not retained, so both new arms explicitly use
fresh optimizer state. This has not yet been implemented or executed as a fit.

## Fixed evaluation and limits

The proposed NoUpdate and both updated arms each receive two actual calls per
task, max 384 generated tokens per call, on the six A-retention and the existing
six upstream development tasks. Report first, final, selected, recovered and
regressed outcomes, including every format failure, and all training/loading/
generation/verifier cost windows. The current six B tasks are already exposed
development material; they cannot become a future independent confirmation panel.

The A criterion for advancing the mechanism is fewer post-success regressions
without losing the observed recovery opportunities or final A successes relative
to the matched all-observed control. B is reported without selection or tuning.
An A improvement alone does not establish generalization, scientific confirmation,
native adoption or settlement. The research NoUpdate decision is retained until
separate new evidence justifies any later promotion.

`build_corpus.py` opens only the A-training records and the current student's A
outputs from the exact original archive index. `prepared/CORPUS.json` contains
the original-output bindings, actual verification, target-credit labels and
explicit zero new-model-call count. These are the same six source groups and
zero authenticated independent users.
