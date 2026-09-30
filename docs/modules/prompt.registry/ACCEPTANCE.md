# prompt.registry independent acceptance

Independent acceptance is deliberately separate from source implementation and
four-lane qualification.

## Required control

The workflow `.github/workflows/hepta-prompt-registry-acceptance.yml` uses the
protected environment `prompt-registry-independent-acceptance`. Repository
administrators must configure that environment with required reviewers who are
not the implementation pull-request author. Without that external protection,
no acceptance artifact is authoritative.

The workflow also fails when the invoking actor equals the pull-request author,
when the pull-request head no longer equals the requested source SHA, or when
the qualification summary is missing any exact identity.

## Bound evidence

An acceptance statement binds:

- source SHA and exact source tree;
- base SHA and bound synthetic-merge SHA/tree;
- qualification workflow SHA/ref and qualification run/attempt;
- `Cargo.lock` SHA-256;
- runner and target triple for every lane;
- all four receipt SHA-256 values;
- all four complete lane-artifact content digests;
- acceptance workflow SHA/run/attempt, protected actor, PR number, and PR author.

Acceptance does not activate the product, authorize deployment, dispose of
historical payload bytes, or release the module. Those fields remain false in
the statement.

## Invocation

After one four-lane run has produced a successful summary, an independent
reviewer may manually dispatch the acceptance workflow with the exact
qualification run, attempt, source SHA, and pull-request number. The workflow
re-downloads the immutable summary from that run and emits a separate acceptance
artifact. It never edits the source branch.
