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
`self-hosted` and `objective-target-host-ephemeral` labels. The infrastructure
owner must attest the ephemeral lifecycle; a routing label alone proves neither
host provisioning nor workspace destruction. Its generated receipt is only an
unsigned template with `accepted=false`; the selected host-profile and storage
qualification authorities must evaluate budgets and durability before issuing the
real receipt.

Receipt bytes are external data. They cannot be committed inside the candidate
whose exact commit/tree they bind: doing so creates a self-referential SHA
dependency. The protected verifier requires `--receipts-root` outside both the
trusted and candidate checkouts:

```sh
python3 trusted/scripts/hepta-objective-protected-release-verify.py \
  --trusted-root trusted \
  --candidate-root candidate \
  --candidate-sha <full-immutable-candidate-sha> \
  --receipts-root /external/receipt-artifact-directory \
  --output /external/objective-release-readiness.json
```

The manually dispatched `Hepta objective release gate` workflow uses the
protected `objective-production-release` environment. Its inputs are
`candidate_sha`, `receipt_run_id` and `receipt_artifact_name`; it downloads that
same-repository artifact into a separate temporary directory and uses only the
protected trusted verifier. The run/artifact selection identifies transport
provenance, not an authenticated acceptance issuer.

A consistent digest-linked unsigned chain yields
`receiptChainConsistent: true`, `receiptAuthenticityVerified: false` and
`externalAuthorityVerification: required`. `releaseGranted` and the four
release truth fields stay false. Independently verifiable external issuer and
acceptance evidence remain required. The verifier does not edit source truth,
activate a deployment, promote a canary or appoint a release authority.
