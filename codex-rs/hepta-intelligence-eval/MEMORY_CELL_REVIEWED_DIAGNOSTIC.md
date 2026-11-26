# Audited evidence and the unchanged-reader diagnostic

The evidence ledger, authority, selected serving and rollback owners are unchanged.
This continuation does not grant independent review, train a policy or promote a
model. It repairs the opt-in reviewed_bundle execution introduced at c7b6aae6.

## What was reviewed, and by whom

The frozen eight-case input is artifact 11665851771 from run 38041339781 at source
e143e192d355d06b882a53c3af9fb6f98f2f9ed8. The original published eOBQA three-vote
records, all original options, sources, answers and cases are preserved. There
were 22 disjoint eligible components under the prior publisher profile, not the
24 needed for its full learning/transfer horizon. The eight-case diagnostic did
not reduce that training horizon.

`data/necessity-source-audit-20261010.json` records a source-only, model-assisted
review of those exact eight cases and their existing candidate sentences. It was
written before examining this cohort's reader outputs. It is authored by the
implementation assistant, **not an independent human**. Five premise groups are
provisionally suitable for diagnostic use; three are flagged for a missing premise,
redundancy/questionable target, or ambiguity. The ledger contains exact bytes,
reasoning summaries, limits, source pins and all pending human dispositions.

No missing fact was synthesized, no publisher answer changed and no case was
replaced with an easier one. "Minimal" here is a provisional assertion about
premise groups under declared linguistic assumptions, not a proof that every byte
is necessary, nor independent confirmation of real-world truth.

`prepare_source_audit.py` validates the full cohort and stages the existing fixed
retrieval controls without using review decisions. It then exports only the five
provisional claims through `reviewed_bundle.py`; unavailable reviews remain in
the full census. `independent-review-inputs.json` is a separate worklist without
assistant dispositions, gold answers, reader responses or scores. All eight
independent judgments are pending. A reviewer must derive and justify their own
answer and requirement groups, then use the existing review/authority owners.

## Pinned actual execution

The projection-only CLI remains supported. The optional model mode now REQUIRES
an external hash for the inventory file as well as the plan, reviews, withdrawals
and labels. Previous commands that omitted `--inventory-sha` must add it:

```sh
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/reviewed_bundle.py \
  PLAN.json REVIEWS.json WITHDRAWALS.json NEW_OUTPUT_DIR \
  --plan-sha PLAN_SHA256 --reviews-sha REVIEWS_SHA256 \
  --withdrawals-sha WITHDRAWALS_SHA256 \
  --reader MODEL_DIR --inventory INVENTORY.json --inventory-sha INVENTORY_SHA256 \
  --labels LABELS.json --labels-sha LABELS_SHA256
```

`reviewed_diagnostic.py` uses the same FrozenBundleReader and existing run_reader.
The source pin is checked before model loading. QA label bytes are hash-checked,
but labels are not parsed by the reader: the existing runner opens annotations
for QA scoring only after raw answers have been durably recorded. Ordinary
retrieval controls remain unchanged. New full/omission/reversed conditions match
the original empty-control token ceiling (2,048 in this frozen profile), and the
same 64-token deterministic decoder is used. Reader size is a separate diagnostic
axis, never a MemoryCell gain claim.

Every model call rechecks the externally pinned withdrawal view before and after
inference; a changed file or revoked source prevents a success receipt. This is
a bounded offline experiment, not an authenticated live production revocation
feed. Hashes certify bytes, not the publisher's semantics or an actor identity.

The existing numeric precondition remains eight complete cases, full and reversed
F1 each >=0.6, and full-minus-empty F1 >=0.1. Missing records, unavailable reviews,
missing scores or mixed reader identities cannot pass. Even a numeric pass here
cannot authorize training: independent source/role admission is separate and is
not supplied by this command. No optimizer is imported or invoked by the new
read-only diagnostic. Existing composition policy code remains unchanged.

## Evidence scope

The read-only workflow `hepta-memory-reviewed-source-diagnostic.yml` executes the
locked full regression environment, stages the same fixed 135M and 1.7B readers,
and generates every available original and reviewed condition. For each reader,
the planned census is 98 records: 72 existing controls, 20 added reviewed reads,
and six explicit unavailable review conditions. No citation is appended after
generation. QA F1, marker presence and independent semantic entailment remain
distinct. Public exposed development cases, order variants, repeated CI and local
execution timestamps are not independent future observations.

Inspect the actual execution commit, artifact inventory and terminal result.
Documentation, source formatting and deterministic reaggregation do not create
new model executions or independent review decisions. The prior temporary
source-writing formatter is now a read-only repository format check; no required
format, owner or Architecture gate was disabled.
