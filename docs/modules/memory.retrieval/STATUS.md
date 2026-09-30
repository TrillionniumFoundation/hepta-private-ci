# memory.retrieval qualification status

This page is an operator entry point, not a manually maintained status ledger.
The repository-controlled policy is
`qualification/memory-retrieval/qualification-policy.json`. The convergence
workflow generates `qualification-manifest.json` for the exact candidate head.
That manifest is the only runtime status observation and contains:

- the frozen implementation-source commit and tree;
- the direct map-only candidate commit and tree;
- the fetched current `main` commit;
- the ordered-parent deterministic merge commit and tree;
- the exact workflow run and attempt identities;
- repository, CodeQL, target-host and calibration evidence state;
- independent-acceptance and external-retention state; and
- the activation mode and fail-closed production claim boundary.

No `YES`/`NO` prose in this document, pull-request body, implementation map or
workflow summary is an independent readiness fact.

## Candidate seal and generated projections

One candidate consists of exactly two commits:

1. a frozen source commit containing code, policy, workflows and documentation;
2. its direct child changing only
   `docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json`.

`scripts/hepta_memory_retrieval_refresh_map.py` is the single generator for the
map and candidate identity. At a source commit it emits a `proposal`; at an
exact map-only child it verifies the parent binding and emits `sealed`. The
read-only maintenance workflow writes these files outside the checkout and
uploads:

- `IMPLEMENTATION_MAP.json`;
- `candidate-identity.json`;
- `pr-identity.md`; and
- `SHA256SUMS`.

The pull-request identity section is a projection of this seal, never an
authority. A source change invalidates the old map, candidate head, approvals,
check observations and PR projection at once.

## Current activation boundary

The checked-in policy keeps `activationMode` at `compatibility`. Source,
structural and contract checks do not authorize canary, required mode, release
or deployment. The generated candidate seal deliberately keeps:

```text
repository_checks_satisfied = false
implementation_ready = false
production_ready = false
merge_ready = false
```

until the exact map-only candidate obtains one coherent successful
qualification set. Production claims remain false after repository qualification
until every external gate is independently accepted.

## Source observation sequence

1. Commit source, workflow, documentation and policy changes.
2. Let the read-only maintenance workflow generate the proposal artifact for
   that exact source SHA.
3. Commit only the generated
   `docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json`.
4. Verify that the resulting head is the direct map-only child and that the
   maintenance artifact reports `state: sealed`.
5. Run source-head, current-main and ordered-parent deterministic-merge
   qualification for that exact candidate.
6. Generate `qualification-manifest.json` from one coherent workflow cohort and
   update the PR identity projection from the sealed artifact.
7. Never reuse a passing result, approval, map or projection from another SHA or
   workflow attempt.

The map object-binds the complete retrieval source tree and every mandatory
critical object. The exact candidate identity binds the broader workspace,
workflow, script, documentation and qualification inputs. Neither artifact is a
substitute for current execution evidence.

## Evidence that remains external

The manifest must keep `production_ready` false until all external gates are
satisfied by separate authorities: a named protected target host with at least
100 observations per workload case, a qualified production encoder and durable
index/lifecycle backend, hard worker isolation, independently governed immutable
raw-evidence retention, canary and rollback receipts, and independent human
approval of the exact head. GitHub-hosted structural probes and 90-day
artifacts are useful repository evidence, but they do not satisfy those
external gates.

## Workflow mutation boundary

All `hepta-memory-retrieval-*.yml` workflows are read-only. The workflow-policy
check rejects `pull_request_target`, repository write permission, persisted
checkout credentials, `git push`, and GitHub API mutations. Candidate seal
generation writes only to the runner temporary directory. Source formatting,
the map-only commit and PR projection publication remain explicit reviewed
actions; CI never edits or pushes the candidate branch.
