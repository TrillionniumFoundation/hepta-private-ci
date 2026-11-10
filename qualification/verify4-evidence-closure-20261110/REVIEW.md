# Independent review and resolved counterexamples

This is a controlled engineering record. Neither reviewers' agreement nor these
fixtures constitute independent field tasks or independent domain adjudication.

## Resolved before final joint qualification

1. A checker-effects table/cost/version could change while preserving the old
   model identity. Construction and all consuming paths now recheck the actual
   content, schema, group counts and digest.
2. RiskTable cells and missing-label counts could change under the same v1
   identity. The v2 identity binds both training-label denominators and requires
   an explicit refreeze; mutation is rechecked at prediction.
3. Matched analysis admitted reviewability without authenticated assignment
   design, with incompatible within-cluster allocations, or with exactly zero
   net benefit. These three actual before/after counterexamples now refuse.
4. A label authenticator could alter the object after checking it. Ingress and
   recovery now compare exact canonical serialization to the pre-callback label.
   Ordinary Python equality was also insufficient because `False == 0` and
   `3 == 3.0`; explicit numeric-type-alias regressions cover that bypass.
5. A stale deferred choice could hide a missing scheduling decision at a new
   frontier. Only a choice for the current frontier supports unchecked/abstained;
   old completed checks are separately marked stale exposure.
6. A repair intent could be inserted after its child committed an event because
   the child transaction had already been released. Both create and record now
   keep the child writer lock through the explicit parent commit. An independent
   trace verified child exclusion at INSERT and actual COMMIT, plus visibility of
   the committed parent event before child unlock. Hardlink aliases refuse.

The first integrated diagnostic run had one test error because a former dispatch
fixture constructed a stale model outside its expected rejection boundary. The
test now deliberately constructs a malformed restored object to exercise the
dispatch boundary; construction and consumption both refuse stale contents.
The failure log is preserved, followed by the final 226-test passing run.

## Source and formatting boundary

The full local joint run used the exact pre-format bytes retained in
`ENGINEERING.zip/tested_source`; those bytes stayed unchanged during all three
commands. Repository-required `just fmt` then completed. Its current scope does
not register experiments/qualification Python, so pinned Ruff 0.15.13 explicitly
formatted and checked all 16 changed Python files.

Fourteen changed files retained identical raw ASTs. In `shadow_risk.py` and
`shadow_schedule.py`, Ruff changed only function-docstring indentation. Their
full ASTs match after applying `inspect.cleandoc` to docstrings; executable nodes
are unchanged. `FORMAT.json` keeps the raw mismatch rather than claiming all
raw ASTs are identical. Local tests were not rerun after formatting, in accordance
with repository instructions.

Because `scheduler_identity()` also hashes raw source bytes, the formatted
published head needs its own exact-head CI. Local pre-format dispatch identities
must not be relabeled as identities of the published source. The workflow already
checks out the explicit PR head and retains source commit/tree and original logs.
All field-effectiveness, full-cost and whole-repository gates remain separate.
