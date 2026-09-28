# objective.compiler final-candidate qualification trigger

This source-controlled marker creates a user-authored branch event after ordinary source and implementation-map authoring have completed. GitHub intentionally suppresses recursive workflow events for pushes made with a workflow `GITHUB_TOKEN`; the marker therefore triggers the read-only exact-candidate and qualification-host workflows on the final branch tree without allowing either workflow to modify source.

The marker is not a pass receipt and grants no implementation, acceptance, activation, promotion or release authority. Only the immutable workflow inputs, observed command results, log/artifact digests, evidence projection and external acceptance records determine those states. Missing, queued, cancelled, incomplete or failed execution remains unverified.
