# Declared larger-model follow-up: strict delivery failed

The one declared follow-up used frozen `Qwen/Qwen2.5-0.5B-Instruct`, revision
`7ae557604adf67be50417f59c2c2f167def9a775`, with the same disclosed tasks,
prompts and strict parser as the earlier pilot. The source/materialization freeze
was published in [#4979](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4979),
commit `3006bddacab081bafbd533f5a276d475ca3cb1b7`, before this model ran.
No further model search is part of this protocol.

## Complete outcome

| Arm | Episodes | Delivered | Correct under the registered contract | Model calls | Tool calls | Inclusive episode wall seconds | Child CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct answer | 8 | 0 | 0 | 8 | 0 | 154.042753 | 220.168965 |
| One model-selected tool | 8 | 0 | 0 | 8 | 0 | 144.853389 | 203.658322 |

All 16 actual task requests returned matching model identities and successful
transport envelopes. Fifteen responses failed exact JSON parsing; one was valid
JSON with an invalid tool-payload structure. No SQL/source tool or semantic
verifier ran. These are delivery failures, not independently scored wrong
answers. The protocol was not changed to remove fences, repair plans or retry.

The separate qualification also returned a Markdown JSON fence around `[1]`,
rather than exact JSON. Its transport completed, but its requested output format
failed. It is not counted as a successful task. The predefined procedure still
executed every task, irrespective of qualification quality.

There were 17 real model responses including qualification. The main run used
2,116 input and 497 output tokens, 298.919945 outer wall seconds and 423.827287
child CPU seconds. Qualification consumed another 14.931039 outer wall seconds
and 53 input / 11 output tokens. Request/host/worker/generation envelopes overlap;
they cannot be added as separate time charges. Host currency cost remains
unknown and paid external model API calls remain zero. The shared runtime
installation is counted once across both studies; both acquisitions and both
failed studies remain part of the development effort.

## Receipt reconstruction

The internal follow-up auditor adapts the preceding independent audit machinery.
It is not a new external or independent review. It directly reconstructs
494,032,768 float32 parameters from 290 BF16 tensors, matching every recorded
before/after fingerprint:

```text
815634c0b4c921ad07b4a32437ff872342e745b15a386f6ca8f5a2d4974e0c13
```

All 17 request payloads, observed identities, output token decodings, durable
intent/terminal pairs and episode records reconcile. The 19 frozen remote source
blobs match the pre-inference commit; all 67 audited inputs remain unchanged.
The audit performs no model forward, tool call or semantic verification.
Source binding and receipt consistency do not establish independent host attestation.

`evidence/execution/` retains all 37 original run files in two deterministic
archives with original per-file hashes. `restore_execution.py` verifies and
restores them without overwriting an existing destination. The audit code,
receipt and immutable remote anchor are in `evidence/audit/`.

Any later, explicitly declared wire-format adapter is a separate development
contract. It must preserve these failures, freeze its own parser and runner
before execution, and retain all new outcomes. It cannot retrospectively improve
these scores or turn the reused two-source task bank into independent validation.
Actual tool success, NDU superiority, positive net benefit and a new RL result
remain unestablished by this follow-up.
