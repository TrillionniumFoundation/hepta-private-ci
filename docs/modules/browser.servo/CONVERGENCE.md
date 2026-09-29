# browser.servo convergence authority

`QUALIFICATION.json` is the sole tracked source for qualification gates and lifecycle claims. It is non-self-authorizing: a tracked file cannot contain the SHA of the commit that contains itself, so read-only CI attaches the observed commit and tree at runtime.

`IMPLEMENTATION_MAP_V2.json` is the canonical implementation map. The pre-existing `IMPLEMENTATION_MAP.json` remains a compatibility view for historical tooling; its former `repositoryControlledSourceBoundaryGapsClosed=true` value is superseded and must not be used as qualification evidence.

Generated/read-only projections are `QUALIFICATION_STATUS.md`, `RELEASE_MANIFEST.json`, and `ARTIFACT_PROVENANCE_INDEX.json`. Exact-head and deterministic synthetic-merge receipts bind these files to one observed source identity. A final gate accepts only terminal success; failed, cancelled, or skipped required work is non-evidence.

The following claims remain false until their designated independent evidence and decisions exist: `repositoryControlledSourceBoundaryGapsClosed`, `productExecutionComplete`, `deploymentQualificationComplete`, `independentAcceptanceComplete`, `productionImplementation`, `productExecutionProved`, `independentAcceptance`, `activation`, `promotion`, and `release`.
