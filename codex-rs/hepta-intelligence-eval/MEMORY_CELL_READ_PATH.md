# Evidence-set reading, reviewed support and past-only memory sessions

Base source: `bba04e2cd9c575023c0744c4942563141a6a26f1`.
This continuation reuses `EvidenceBundle`, `FrozenBundleReader`, current source
validation and the existing native audit. It does not change production wire
contracts, default serving, model adoption, signing or owner authority.

## What the inherited actual experiment establishes

Run `38016862229` executed 135M/360M/1.7B frozen readers on the same 72 planned
conditions per tier (two native questions per benchmark plus two authored controls,
12 conditions each). Each tier produced 67 answers, five explicit unavailabilities
and zero execution errors. Larger readers were not automatically selected.
The LongMemEval publisher-source conditions needed 11,370 and 6,241 input tokens
on the 1.7B reader and exceeded the 4,096-token cap. They do not establish an oracle
ceiling. Three sizes running successfully does not mean one is adequate.

The read-only matrix, raw answers and exact source files are retained. Public
cases already exposed in development cannot be promoted to fresh final tests.

## Reviewed minimal evidence, without invented independent reviewers

`reviewed_bundle.py` accepts an externally pinned `hepta.minimal-evidence.review.v1`
package for an already frozen `hepta.bundle-diagnostic.plan.v1` plan. Each review
binds the exact query, original source frontier, reviewer identifier, review time,
byte ranges/content hashes and named necessary requirements. Full support and
leave-one-requirement-out conditions use unchanged source bytes. Intersections,
UTF-8 splits, missing requirements, changed scope/time and withdrawn roots reject.

The ordinary retrieval conditions are copied unchanged. There is no query answer
field in the review schema. Missing reviews remain unavailable; whole publisher
sessions never silently become minimal sufficient evidence. The output preserves
`independent_review=false` and `sufficient_context_certified=false`: this Python
projection cannot authenticate the reviewer's claim. Existing signed owners must
perform real identity, purpose, independence and authority validation separately.
Authored test fixtures are identified explicitly and never counted as human review.

```sh
python scripts/memory_cell/reviewed_bundle.py \
  plan.json external-reviews.json current-withdrawals.json reviewed-plan.json \
  --plan-sha PLAN_SHA256 --reviews-sha REVIEW_SHA256 \
  --withdrawals-sha CURRENT_WITHDRAWALS_SHA256
```

Run the resulting plan through the EXISTING `bundle_trial.py run` with the same
reader and labels. Measure the complete prompt normally; oversized reviewed sets
are unavailable rather than silently trimmed. Oracle projections cannot enter
`FrozenMemorySession`'s normal selector path. Changing model size remains a capacity
diagnostic, not a gain credited to a cell. There is no new claim of 99% semantics.

## A curriculum about sufficient evidence rather than forced answer strings

`memory_curriculum.project_curriculum` projects historical external review claims
into full/missing-prerequisite pairs. The question stays identical. Missing review
is unknown, not a negative; omitting a premise does not assert the world has no
answer. All original sources, review times and question times must be inside the
past-only cut; forbidden question/family/source sets reject before projection.
No gold answer text or future task labels are synthesized or consumed. This does
not execute an optimizer. Temporal, entity-relation and procedural semantics must
come from actual review or executable outcome owners; a named requirement alone
cannot establish them.

Use these pairs to train a small evidence-set/sufficiency policy ONLY after the
frozen reader's actual reviewed-context results justify that step. Keep reader
weights fixed and compare equal candidate views. Do not train another refusal
adapter merely because this projection exists. Independently reviewed real-task
examples and actual procedural outcomes are still needed.

## Freeze experience first, expose task later

`frozen_memory_session.freeze` consumes only past Documents and already-produced
opaque policy bytes. It commits exact sources, policy ancestry, reader identity,
source commit and predecessor reference with a create-only, synced READY marker.
`FrozenMemorySession.answer` receives the Question later, checks its declared time
and scope, logs exposure before inference, and holds a nonblocking OS writer lock.
It cannot update the policy. Reader/artifact drift and current source withdrawal
are checked before execution and after generation. Failed calls retain an explicit
failure without releasing the generated answer. An interrupted attempt is
indeterminate and cannot automatically trigger a second model call on recovery.

Replay requires the exact snapshot AND previously obtained result hashes and
checks CURRENT withdrawal again. Rolling back to an old file cannot bypass a
withdrawal supplied by the current owner. Any withdrawn snapshot source invalidates
this conservative experimental view; rebuild is necessary even for unrelated roots.

This is a local experiment journal, not a production store or a distributed lock.
The external cutoff is not a trusted clock; equal event times and forged caller
metadata do not create independent prospective observations. A callable selector
must obey the no-update contract; Python cannot prove arbitrary external globals
are isolated. Production mutation fencing/cancellation still belongs to the
existing owners. Logs do not mint consent or adopt selected-LoRA.

## Runnable conformance and interpretation

`frozen_session_probe.py` exercises the actual frozen reader on four authored
single/set controls, commit-before-task ordering, re-opened read parity and current
withdrawal rejection. It never executes a model-generated command. Replay does not
perform another generation. Sources are authored controls, NOT observed compiler
outcomes, real future tasks, trained snapshots or independent data. Actual index
and write time are reported; policy training is zero because no optimizer runs.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_reviewed_bundle.py' -v
python3 -m unittest discover -s scripts/memory_cell -p 'test_memory_curriculum.py' -v
python3 -m unittest discover -s scripts/memory_cell -p 'test_frozen*.py' -v
```

The read-path workflow runs exact-source regressions and a separate real pretrained
probe. A temporary same-repository formatter may prepare a separate review branch;
it never updates main or the PR ref and removes itself from its candidate commit.
All required CI checks remain required. Unit fixtures are not pretrained results.

Remaining qualifications: a real reviewed minimal-sufficient corpus, useful shared
reader oracle accuracy, learned policy task gains, full real executable experience
streams with retention/cost reporting, real future windows and independent
production cutover/recovery. None is certified by this local protocol or probe.
