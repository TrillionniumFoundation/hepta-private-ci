# Prospective B comparison: structural admission only

Status: **NOT_READY_EXTERNAL_SOURCE_REVIEW**. No new model, training, verifier or
business execution has occurred. No independent tasks have been admitted.

## Existing work and scope

E2 #6678 preserves the completed exposed A6/B3 run. Its initial adapter has no
same-protocol B measurement. #6672/#6680/#6681 address E4 shared-pool execution
and strong same-call controls, not this missing prospective baseline. This
change does not modify those runners, old scores, frozen receipts or sources.

The new `prospective_b.py` performs structural freeze/readout checks. It is not
a GPU runner or an independent-source authenticator. A hash authenticates
neither task authorship nor disjoint source ancestry. A dishonest source-group
label can pass structural checks. The explicit NOT_READY state therefore never
becomes READY merely because a supplied plan or receipt passes validation.

## Before any numerical execution

1. Obtain a genuinely new panel from sources outside the retained development
   lineage. Independently inspect provenance, ancestry, prior exposure, access
   history and the sealed source bytes. Archive that review and source material
   with access controls that prevent B answers from entering training. Merely
   inventing different task IDs, seeds, branches or hashes is insufficient.
2. Freeze all three model identities: unchanged initial adapter, candidate, and
   matched control. Pin source closure, runtime, verifier/protocol, information
   made available to each arm and full B panel. All arms must receive identical
   evaluation information; differing training treatments are separately declared.
   The current checker requires three distinct identities, so a duplicate control
   is rejected rather than counted as another scientific arm.
3. Commit the plan digest to independent custody BEFORE any B query. `freeze`
   creates its local file exclusively but cannot establish trustworthy chronology
   or prevent directory deletion. Supply the custody-pinned digest to `review`.
   Do not read that expected value from the mutable candidate directory.
4. Evaluate initial, candidate and matched control under the same protocol and
   task denominator. Keep failures, rejected actions and interrupted work. Do not
   train, select a new arm or tune caps using the resulting B scores. The current
   selection rule is report-all/no-adoption, not a decision to promote a model.

No actual independent panel, models for a new experiment, or authenticated custody
review is supplied here. Numerical execution remains blocked on these inputs.

## Costs and inference

Freeze a shared vector of caps before the experiment. Record measured model and
verifier calls, input/output tokens and training tokens, including preparation,
failed attempts and control acquisition in the declared cost scope. Missing meters
are null, never zero. This checker rejects missing dimensions and retains unknowns.
It distinguishes shared caps, measured-vector equality and complete physical cost.
Even equal measured vectors do not prove equal GPU time, money, energy or total
system cost. It never claims full-system cost completeness.

The unchanged initial arm normally has zero new training cost. Do not add dummy
work merely to make its vector match: report its accuracy/cost point separately.
For trained candidate/control, predefine the same budget and information access,
then report actual costs. If actual costs differ, do not label the outcome a
same-cost advantage; design a separate prospective budget comparison instead.
Repeated cold evaluations and multiple attempts do not add independent tasks.
Use source-group-aware paired analysis only after independent source review and
an adequate prospectively selected panel, not iid inference over retry receipts.

## Verification

Six synthetic standard-library controls exercise create-once freezing, external
pin mismatch, lineage overlap/exposure, information mismatch, missing/null costs,
unequal actual costs under equal caps, duplicate receipts, wrong model/run,
unexecuted success, over-budget and incomplete outcomes. They establish checker
behavior only. Run:

```
cd scripts/cell_experiments
python -m unittest -v test_prospective_b
```

Repository-wide formatting/CI and real-model execution must be reported separately.
