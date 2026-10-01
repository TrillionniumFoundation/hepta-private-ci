# control.runtime current-state contract

`CURRENT_STATE.json` is the canonical maturity fact source for this module. The implementation map remains the operation and source-symbol inventory; prose documents explain design and recovery semantics. Neither prose nor an implementation-map `state` string may advance a maturity gate independently.

Each subsystem records these stages separately:

1. `designDefined`
2. `sourcePresent`
3. `guardedPublicEntry`
4. `productCallsiteIntegrated`
5. `exactSourceTestsPassed`
6. `fixedMergeCandidatePassed`
7. `targetHostRecoveryPassed`
8. `independentlyAccepted`
9. `activated`
10. `released`

The order is evidentiary, not a promise that every subsystem must become a production writer. A read-only product callsite may be integrated while global effect execution remains uncomposed. `sourcePresent` never implies target-host recovery, independent acceptance, activation or release.

The candidate workflow resolves the exact pull-request source commit and deterministic synthetic merge at run time. It validates the state schema before formatting, tests, all-target compilation and strict lint, then fails closed unless every independent check succeeds and the tracked tree remains unchanged. Exact commit and tree identities live in workflow artifacts; they are not written back into source by a qualification job.

Independent steps use `continue-on-error` so later checks still run. A GitHub
step's displayed conclusion may therefore be successful after its command failed.
Use the recorder's command exit/status, the step outcome consumed by the final
aggregation, and the final job result to assess qualification. A passing unit
suite does not establish that later integration binaries passed.

Externally governed gates stay false in source. Target-host recovery requires actual multi-process failure testing on the named host. Independent acceptance, operator acceptance, canary, activation, promotion and release require their respective external evidence and cannot be self-certified by this repository candidate.
