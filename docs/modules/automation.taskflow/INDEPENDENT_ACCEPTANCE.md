# automation.taskflow independent acceptance

This contract applies to the schema-v19 durable TaskFlow owner and every later compatible candidate that preserves its V1 identities and store semantics.

Repository-controlled implementation and host qualification do not grant release authority. Independent acceptance is a separately signed evidence class and must be issued by a principal distinct from the implementation principal.

## Evidence chain

The acceptance payload binds all of the following immutable values:

- candidate commit and tree;
- successful `automation-taskflow-focused` run ID and command-receipt digest;
- successful selected-host run ID and selected-host receipt digest;
- target deployment profile;
- provider and terminal-observer identity digests;
- final-use trust-root and revocation-head digests;
- implementation principal, acceptance principal, acceptance key fingerprint, UTC timestamp and nonce.

The canonical signed bytes are UTF-8 JSON with keys sorted and separators `,` and `:` with no insignificant whitespace. The signature is Ed25519 over those exact bytes.

## Protected verification environment

`.github/workflows/automation-taskflow-independent-acceptance.yml` runs in the protected `automation-taskflow-independent-acceptance` environment. That environment supplies:

- `AUTOMATION_ACCEPTANCE_PUBLIC_KEY_PEM` as a secret;
- `AUTOMATION_IMPLEMENTATION_PRINCIPAL` as an environment variable;
- `AUTOMATION_ACCEPTANCE_PRINCIPAL` as an environment variable;
- independent reviewers who are not the implementation principal.

The workflow downloads the successful focused and selected-host artifacts, checks the exact candidate identities, loads the acceptance envelope from an immutable evidence commit, and calls `scripts/verify_automation_taskflow_acceptance.py`. A self-signed envelope, altered receipt, different provider profile, stale revocation head, untrusted key or same-principal signature fails closed.

## Envelope shape

```json
{
  "schema": "hepta.automation-taskflow.independent-acceptance-envelope.v1",
  "payload": {
    "schema": "hepta.automation-taskflow.independent-acceptance-payload.v1",
    "module": "automation.taskflow",
    "candidateCommit": "<40 lowercase hex>",
    "candidateTree": "<40 lowercase hex>",
    "focusedRunId": "<GitHub run id>",
    "selectedHostRunId": "<GitHub run id>",
    "focusedReceiptSha256": "<64 lowercase hex>",
    "selectedHostReceiptSha256": "<64 lowercase hex>",
    "targetProfile": "<selected profile>",
    "providerIdentitySha256": "<64 lowercase hex>",
    "terminalObserverIdentitySha256": "<64 lowercase hex>",
    "finalUseTrustSha256": "<64 lowercase hex>",
    "revocationHeadSha256": "<64 lowercase hex>",
    "implementationPrincipal": "<implementation principal>",
    "acceptancePrincipal": "<independent principal>",
    "acceptanceKeySha256": "<trusted public-key DER digest>",
    "decision": "accepted",
    "independentAcceptance": true,
    "acceptedAtUtc": "<ISO-8601 UTC Z timestamp>",
    "nonce": "<unique acceptance nonce>"
  },
  "signatureHex": "<128 lowercase hex>"
}
```

## Gate semantics

A verified envelope establishes only `independentAcceptance = true` for the exact evidence chain. It does not silently activate, promote or release the candidate. Those decisions remain explicit, separately authorized transitions. The verifier therefore emits:

```text
independentAcceptance = true
activation = false
promotion = false
release = false
```
