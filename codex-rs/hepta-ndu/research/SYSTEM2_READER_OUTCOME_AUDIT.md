# New-question Reader outcome audit and blinded review handoff

Generating experiment: source `920aede3ccc4c39ced56c90c6c6936a7245c533c`,
tree `a58aaff0da1cc548f9fff1d7788b7028a8537585`, run **38189628380**.
GitHub reports completed/success. Artifact **11721757214**, 5,747,664 bytes,
external ZIP SHA256:
`53dff155f79d4b333ba30060022cc38d351807993f09812ee94e0d8f5f24aee3`.
Workflow completion alone does not establish the candidate's answer quality.

This stage does not change the candidate, question cohort, support selection,
Reader, scores, or any prior experiment. It adds a stdlib-only read-only audit of
that exact artifact. No archived Python executes, no pickle is loaded, no model
is staged, and no new Encoder/Reader call is made. The historical archive reader
provides bounded regular-file parsing, the external ZIP pin, and manifest checks.
The auditor's generating source remains distinct from the model experiment SHA.

The audit checks original source blob identities, the 12-support/48-query plan,
all 384 expected arm/query positions, the raw answer seal, unmodified scoring
copies, Reader profile and token limits, successful call counters, original UTF-8
evidence spans, delivered evidence receipts, encoding-phase records, and frozen
state-file hashes. It recomputes recorded F1 aggregates and bounds, not semantic
correctness. Parameter equality is not numerically replayed by this stdlib tool;
transport/state hashes and phase receipts do not prove independent observation.

Reports separate source-membership hits from diagnostic token-F1; known-score
means from full-planned bounds; family breakdowns from aggregate totals; and
answerable from native-unanswerable rows. Failures and unknown scores are never
silently dropped or converted to successful answers. Identical recorded Reader
requests must have identical original outputs; a violation fails the audit,
rather than being credited to a learning policy. Actual tokens and elapsed time
are reported, not declared equal compute or production cost.

## Review handoff, not an authored verdict

`blind-review.jsonl` deduplicates exact query/input/output tuples and removes arm
names and diagnostic scores. It contains original question text, selected source
bytes, labels, and the unchanged answer. `review-arm-map.json` separately maps
each original successful attempt to a case ID so deduplication cannot shrink the
experimental census or hide costs. Keep this mapping out of the reviewer's view.
The review artifact is a research handoff, not a persistent Library share.

Reviewer identity, reference answer and semantic verdict remain null; independent
review is false. Evidence-support judgment, citation entailment, task truth and
sufficiency must be distinguished. A reviewer can often judge whether a claim is
supported by the delivered fragments; absence of a supplied reference/full history
may still prevent determining the true answer or global evidence sufficiency.
Do not fill those unknowns with a model's signature or an inferred gold answer.

## Reproduce and distinguish evidence levels

```sh
python3 -m unittest discover -s scripts/memory_cell \
  -p 'test_system2_reader_outcome_audit.py' -v
python3 scripts/memory_cell/system2_reader_outcome_audit.py \
  /path/to/original-new-question-artifact.zip /new/audit-output
```

Ten new fixture tests cover counter/status integrity, missing rows, unmodified
answers, unknown-score bounds, failed runs, label/feature drift, repeated-input
consistency, model profiles, token counters, and support/query isolation.
The separate push workflow tests then audits the pinned existing artifact and
prints aggregates to its logs. The inherited full regression/static workflow is
unchanged and retains its own status. No test has been claimed passed merely
because its source or workflow was created.

Local execution in this continuation failed at the container-service level;
no local tests, artifact extraction, formatter, or numerical replay succeeded.
The audit intentionally runs in the connected GitHub environment instead. Exact
hosted logs/results, once read, are the evidence; queued status is not completion.
All production/independent/Reader-adequacy gates remain false. No main merge,
serving default change, human-review fabrication or NDU utility calibration.
