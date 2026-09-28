# memory.retrieval qualification status

This page is an operator entry point, not a manually maintained status ledger.
The repository-controlled policy is
`qualification/memory-retrieval/qualification-policy.json`. The convergence
workflow generates `qualification-manifest.json` for the exact candidate head.
That manifest is the only runtime status observation and contains:

- the exact source commit and tree;
- the fetched current `main` commit;
- the ordered-parent synthetic merge commit and tree;
- the latest exact-head repository and CodeQL check observations;
- target-host E2E and calibration evidence state;
- independent-acceptance and external-retention state; and
- the activation mode and false production claim boundary.

## Current activation boundary

The checked-in policy keeps `activationMode` at `compatibility`. Source,
structural and contract checks do not authorize canary, required mode, release,
or deployment. Any source change creates a new Git identity and therefore makes
all earlier exact-head approvals and check observations stale.

## Source observation sequence

1. Commit source, workflow, documentation and policy changes.
2. Run `scripts/hepta_memory_retrieval_refresh_map.py --head <exact-source-sha>`
   from a clean checkout.
3. Commit only `docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json`.
4. Let the read-only convergence workflow test the resulting map-only head,
   current `main`, and the ordered-parent synthetic merge.
5. Inspect the content-hashed manifest artifact. Never copy a passing result
   from a different source commit.

The map intentionally object-binds the complete retrieval source tree while the
exact observed commit/tree and deterministic closure inventory bind the broader
workspace, workflow, script, documentation and qualification inputs. Legacy
per-file path accumulation is rejected; the canonical input list comes only
from the policy file.

## Evidence that remains external

The manifest must keep `production_ready` false until all external gates are
satisfied by separate authorities: a named protected target host with at least
100 observations per workload case, independent human approval of the exact
head, immutable raw-evidence retention outside the source publisher's control,
and a killable worker boundary with enforced CPU, memory and allocation limits.
GitHub-hosted structural probes and 90-day artifacts are useful evidence, but
they do not satisfy those external gates.

## Workflow mutation boundary

All `hepta-memory-retrieval-*.yml` workflows are read-only. The workflow-policy
check rejects `pull_request_target`, repository write permission, persisted
checkout credentials, `git push`, and GitHub API mutations. Source formatting,
map refresh and evidence publication are explicit developer actions followed by
normal review; CI never edits or pushes the candidate branch.
