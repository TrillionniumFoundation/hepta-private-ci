# objective.compiler release receipts

This directory is intentionally empty of acceptance receipts in the source candidate.
A source commit, GitHub-hosted CI run, benchmark fixture, generated template, or module
owner statement cannot manufacture production acceptance.

The protected release gate accepts only the complete receipt chain declared in
`docs/modules/objective.compiler/RELEASE_POLICY.json`. Every receipt must bind the
same exact candidate commit and tree, the release-policy digest, its named evidence,
and the digest of each predecessor receipt. The required chain is:

```text
exact-head qualification
-> synthetic-merge qualification
-> selected target-host qualification
-> independent review
-> canary observation
-> rollback authority
-> promotion approval
-> release authority
```

Target-host measurement is produced by the manually dispatched
`Hepta objective target-host qualification` workflow on a runner carrying both
`self-hosted` and `objective-target-host` labels. Its generated receipt is only an
unsigned template with `accepted=false`; the selected host-profile and storage
qualification authorities must evaluate budgets and durability before issuing the
real receipt.

The `Hepta objective release gate` workflow uses the protected
`objective-production-release` environment. It emits release readiness only after
all committed receipts are valid and digest-linked. It does not silently edit
`CURRENT_STATE.json`, activate a deployment, promote a canary, or grant release
authority. Those remain explicit operator-owned transitions.
