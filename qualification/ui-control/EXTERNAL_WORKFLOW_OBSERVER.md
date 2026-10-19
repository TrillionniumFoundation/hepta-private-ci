# External workflow observer

The `ui.control external qualification observer` workflow records the terminal outcome of every completed `ui.control external deployment qualification` run, including runs that fail before a protected verifier can emit its normal stage receipt.

The observer is deliberately **diagnostic, not authoritative**:

- it is triggered by `workflow_run` only after the external workflow has completed;
- it checks out only the observer implementation at the immutable `github.workflow_sha` of the default-branch workflow;
- it never checks out the candidate, executes candidate-controlled code, downloads artifact contents, or references protected secrets;
- it reads only GitHub workflow-run and complete artifact metadata with `actions: read` authority;
- it binds the observation to the exact trusted observer workflow SHA/run as well as the completed source run;
- it rejects truncated or duplicate artifact inventories, records names, sizes, expiry states, and API-provided digests, but does not infer acceptance from their presence;
- every claim in the observation remains `false`, even when the source workflow succeeded.

A normal observation uses schema `hepta.ui-control.external-workflow-observation.v1`. If trusted checkout, runtime setup, API retrieval, or semantic observation fails, an `always()` fallback emits the same schema with failure code `UI_CONTROL_EXTERNAL_OBSERVER_INFRASTRUCTURE`. The fallback preserves the source run identity and candidate SHA when they can be parsed safely.

This observation closes the infrastructure-evidence gap without weakening the canonical stage ledger. Repository qualification receipts, real-backend receipts, deployment-security receipts, independently signed acceptance/security/operations receipts, and production approval remain the only corresponding acceptance authorities.
