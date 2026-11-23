# A selected external-agent session can submit a JSON artifact

This Linux research adapter is an optional local MCP stdio tool for one deliberately selected conversation and task. It accepts only an attempt slot and UTF-8 artifact text under a fresh capability. It writes the proposed artifact itself to one of two fixed owner-private files, reads back the bytes and applies the precommitted `json_artifact/1` verifier. It captures the submitted text and the canonical logical call, without collecting the rest of the conversation. The result measures the effect inside this local sink. Existing operations in another tool or service require their own original evidence.

## Set up one task

The operator prepares a previously unused private directory under a site-controlled parent. Keep the custody files and the producer signing key outside any workspace or shell accessible to an untrusted agent. Restrict the external client to the tool's stdio connection. Unix permissions alone do not isolate programs sharing that owner's unrestricted account.

From the repository root use `PYTHONPATH=scripts` throughout. The transport uses the Python `mcp` SDK and the private handoff uses `cryptography`; the qualification runs with the versions in `.github/workflows/selected-session-mcp.yml`.

Choose exactly these JSON fields in a private `site-plan.json`.

| Field | Operator-supplied value |
|---|---|
| `study`, `session`, `task` | The study SHA-256, the chosen external session identifier and one task identifier. |
| `input`, `expected` | The actual task text and independently known expected JSON structure. |
| `rights_basis` | The authorized basis for recording these selected submitted actions. |
| `producer_public_key`, `policy_sha256` | The enrolled producer's 32-byte Ed25519 public key and policy digest as lowercase hex. Both may be null for observation only. |

```sh
PYTHONPATH=scripts python -m cell_experiments.selected_session_mcp prepare NEW_PRIVATE_DIR site-plan.json
```

Keep the returned `session_capability` private to the selected session. Give the trusted launcher the `scope_sha256`. In that session's MCP configuration use the Python executable, `PYTHONPATH` set to the repository's absolute scripts directory, and the following arguments. Use a session-specific configuration so the capability reaches only this deliberately chosen task.

```text
-m cell_experiments.selected_session_mcp serve NEW_PRIVATE_DIR SCOPE_SHA256
```

The agent explicitly calls `submit_json_artifact` with `session_capability`, `slot` and `artifact_text`. Each slot accepts one immutable submission; retrying identical text returns its original result. For this paired study, the two slots are `failure` and `correction`. The latter opens after an actual unsuccessful first result. A successful first submission remains a single observed success. A second unsuccessful submission remains a failed correction. The tool returns the semantic result and hashes. It accepts no destination, command, URL or historical log.

## Submit the pair for A's original consent

A source runtime with an independently registered issuer signs its actually produced output, under the site's original key association and policy measurement. The issuer signs the canonical UTF-8 JSON of `statement(scope_sha, plan, slot, sha256(original_utf8))` as defined in the module. Its fields bind the scheme, fresh scope, session, task, policy, slot and exact text SHA-256. The issuer supplies a private file keyed by `failure` and `correction`; each entry holds that original `statement` and its detached 64-byte Ed25519 `signature` in lowercase hex. The adapter checks only the signature under the exact key and policy digest supplied in the site plan. It performs no independent registry lookup, hardware measurement or vendor identity check. A commercial agent identity, its actual model weights and a human's account require independent site evidence. The SDK qualification uses an ephemeral engineering key and an authored local policy. Keep the signing key with the producing runtime. Generic clients lacking a trustworthy producer attestation can still observe the tool's own effects; their training proposal remains pending. A transport session, client name, user-supplied model label and teacher score do not establish that attestation.

```sh
PYTHONPATH=scripts python -m cell_experiments.selected_session_mcp handoff NEW_PRIVATE_DIR SCOPE_SHA256 producer-receipts.json
```

The handoff reopens both original artifact inodes and exact byte strings, verifies the producer signatures and requires the registered semantic failure followed by success. It emits `failure.json`, `correction.json`, hash-addressed originals and, last, `proposed-scope.json`. Incomplete receipt input returns `Pending`; a substituted source returns an error. The pair is a prospective proposal for training. The eligible record declaration serves the existing record schema. Only the separate live owner grant authorizes the trainer.

A reviews and submits the exact output of `hepta-paired-consent --print-statement < NEW_PRIVATE_DIR/proposed-scope.json` in their enrolled physical UI. The site custodian must then use the original signed delivery, frozen parent, retention materials and live FD 3/4 to invoke the existing `cell_experiments.paired_source_train` with the same two hashes. Training, independent B arrival, later use and settlement keep their original separate gates.

## Qualification

```sh
PYTHONPATH=scripts python qualification/selected-session-mcp-20261123/qualify.py --archive ORIGINALS.zip
```

The original local Python SDK client executes an authored policy, makes two real MCP calls and receives the genuine sink response before correcting its output. The test records eleven control conditions, passes the resulting pair through the original `paired_source.derive`, and checks the original training entry refuses absent owner handles. The generated archive contains only this engineering case's source evidence, public verification key, signed statements, readbacks and proposed scope. It omits the capability and the private signing key. This qualification contributes zero human participants, weight updates, financial outcomes and observations of third-party effects.
