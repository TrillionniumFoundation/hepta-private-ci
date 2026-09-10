# Lane G repository-owned hardening

This document is the implementation companion to `IMPLEMENTATION.md`. It records
only controls that can be established by repository-owned source. It is not an
independent acceptance, release, activation, deployment, or authority receipt.

## 1. Transaction boundary and persisted state frontier

Every owner mutation enters `BEGIN IMMEDIATE` before reading mutable owner state.
The rule removes the earlier read-before-write race in lease acquisition and
assignment generation. `assignment_generation_frontiers` binds each generation
ID to:

- the exact work-envelope semantic digest and revision;
- the source commit and source tree; and
- the complete active-lease set, including epoch, fence, revision, expiry,
  paths, holder, and semantic digest.

A generation created before frontier binding is rejected as
`unbound_legacy_generation`; reusing a generation ID after the frontier changes
is rejected as `generation_frontier_conflict`. The store publishes schema
version 3 through both `engineering_schema_meta` and SQLite `user_version`.

## 2. Candidate sandbox boundary

A candidate cannot pass by vacuous truth: at least one mandatory check is
required. Candidate execution additionally requires an exact clean source HEAD
matching the envelope base commit.

The execution directory is a detached, local, no-hardlink clone. Its origin is
removed before mutation or testing, hooks and credential helpers are disabled,
and checks receive neither repository credentials nor the source-repository
path in their argv. The source HEAD, tree, worktree status, and refs frontier are
compared before and after execution.

Only the declared mutation path may change. Old and new content are both charged
to the diff budget, including deletion, and both must be strict UTF-8. Checks
cannot rewrite the candidate after its declared mutation. Network isolation is
fail-closed when the envelope requires it; absence or failure of the isolation
primitive cannot produce a passing receipt.

This is a bounded qualification sandbox, not a claim of hostile multi-tenant OS
containment. A production executor remains an external gate.

## 3. Candidate-bound evidence

Exact source and synthetic-merge receipts establish repository identity and
check outcomes. They are deliberately insufficient to cross the review or
integration-decision boundary by themselves.

`CandidateEvidenceBindingReceipt` is separately signed by the `ci_executor` and
binds all of the following in one freshness window:

- candidate ID and candidate semantic digest;
- sandbox receipt digest and base commit;
- exact evidence digest;
- exact-source execution receipt digest; and
- synthetic-merge execution receipt digest.

`bind_candidate_evidence` produces `BoundEvidenceDecision`. Only this bound type
may create a review request or be persisted as an eligible integration decision.
An unbound or cross-candidate receipt is rejected. Even a valid bound decision
still grants no acceptance, merge, activation, promotion, or release authority.

## 4. Authenticated dormant assimilation

The public composition path now requires two authenticated attestations:

1. the external owner signs the normalized consent payload and target identity;
2. the independent sandbox evaluator signs the exact parity receipt, manifest,
   and synthesized operation set.

Unsigned, stale, mismatched, or caller-invented booleans cannot create a
proposal. A successful result remains `dormant_candidate` with activation,
federation, propagation, and authority all false.

## 5. Qualification identity

The Lane G workflow evaluates the exact source head rather than GitHub's
implicit pull-request merge commit. A separate Ubuntu job constructs and tests a
synthetic merge with ordered base/head parents. The workflow also runs:

- the original V2 suite;
- the hardening regression suite;
- the V2 validator and the hardening registry validator;
- module-document, readiness, documentation, and technical-closure validators;
- repository-integrity self-test and changed-range verification; and
- Python compilation plus `git diff --check`.

The workflow runs on Linux, macOS, and Windows for source identity and on Linux
for synthetic merge identity. Its receipts remain qualification evidence only.

## 6. Mature-state interpretation

`MATURITY.json` intentionally separates documentation, source, implementation,
state binding, consumers, qualification, activation, and authority. No source
file, workflow result, or agent statement may collapse those dimensions into a
single word such as “complete.” External gates stay open until their independent
receipts exist.
