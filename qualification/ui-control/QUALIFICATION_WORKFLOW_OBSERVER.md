# Exact-head qualification workflow observer

## Purpose

The `ui.control exact-head qualification observer` records the terminal GitHub metadata for every completed `ui.control exact-head qualification` run. It exists for the failure window in which the source job cannot execute its own `always()` receipt step—for example, runner allocation, checkout, or runtime setup failure before repository scripts are available.

The observer is diagnostic only. It does not replace either `hepta.ui-control.qualification-receipt.v2` receipt, does not update `UI_CONTROL_MANIFEST.json`, and cannot advance any of the seven canonical stages.

## Authority boundary

The observer runs through `workflow_run` after the source workflow is complete and has only `actions: read` repository authority. It:

- never checks out the candidate or any source ref;
- never executes candidate-controlled code;
- never downloads artifact contents;
- never reads repository, environment, or organization secrets;
- reads only the exact run-attempt, job inventory, and artifact metadata from the GitHub Actions API;
- records artifact names, IDs, sizes, expiry states, and API-provided digests without treating their presence as acceptance;
- emits `acceptedEvidence: false` and keeps every qualification, deployment, production, and release claim false.

The workflow itself is loaded from the repository default branch under GitHub's `workflow_run` semantics. The observer therefore becomes active only after this workflow is present on the default branch; an off-main candidate cannot install or alter the trusted observer for its own run.

## Exact attempt and bounded inventory

The observation binds:

```text
source repository
source workflow name
source run ID
source run attempt
candidate head SHA
source event and terminal conclusion
observer workflow SHA
observer run ID and attempt
```

Jobs are fetched from the attempt-specific API endpoint. Jobs and artifacts are paged with hard limits of 1,000 records and 8 MiB per response. A changed `total_count`, missing page, invalid or duplicate ID, duplicate artifact name, oversized field, invalid digest, or truncated inventory fails closed.

For pull-request runs, the observer expects metadata for both:

```text
ui-control-exact-head-<candidate SHA>
ui-control-synthetic-merge-<synthetic merge SHA>
```

For push and manual runs, only the exact-head observation artifact is required because the synthetic-merge job is intentionally not applicable. A successful source workflow with missing expected metadata is recorded as a failed diagnostic observation, not as accepted qualification.

## Receipt

The normal and fallback paths emit:

```text
hepta.ui-control.qualification-workflow-observation.v1
```

The schema is `QUALIFICATION_WORKFLOW_OBSERVATION_SCHEMA.json`. The receipt separates:

- the source workflow's terminal outcome;
- completeness of job and artifact inventories;
- availability of exact-head and synthetic-merge observation artifacts;
- observer infrastructure failure;
- accepted evidence and authority claims.

`acceptedEvidence` is structurally fixed to `false`, as are all fields under `claims`. Only the exact-tree qualification receipts emitted by the source jobs may satisfy repository source or deterministic merge acceptance.

## Failure behavior

If API retrieval or semantic validation fails, an `always()` fallback emits the same schema with:

```text
UI_CONTROL_QUALIFICATION_OBSERVER_INFRASTRUCTURE
```

The fallback retains only bounded event metadata and step outcomes. It does not reinterpret an unavailable observation as a source failure or success.

If the observer runner itself never starts, no workflow can manufacture an artifact; the GitHub workflow-run record remains the external infrastructure fact. This limitation does not weaken any acceptance gate because absence of an observer receipt never counts as passing evidence.
