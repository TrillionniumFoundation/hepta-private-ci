# Native RuleSlot research process

This executable composes the existing learning-artifact owner service, independent
selection verifier, FinalUse authority and durable inference control. It is not
installed in Agentd. Its three distinct private signing keys are qualification
fixtures and must never become product issuers.

Build exact repository sources in a separate directory:

```sh
python qualification/neuron-stem/native-rule-use/build_shadow.py --output /absolute/research-build --offline
/absolute/research-build/codex-rs/target/debug/native-rule-use /absolute/private-research-state
```

The generated provenance records source hashes, native dependency identities,
toolchain and executable hash. The isolated composition build does not establish
that the complete Agentd product builds or qualifies for deployment.

Commands and responses are JSON lines, bounded to 65,536 bytes including newline.
`command` is the operation key; `cmd` is accepted for the initial research driver.

| Command | Input and observation |
| --- | --- |
| `init` | Exact bundle `payload_hex`, `checkpoint_digest`, `rule_revision`, `authority_epoch: 1`, `generation`, `scope_digest`; optional `selection_lifetime_s` from 1 to 3,600. Publishes exact bytes and signed CURRENT through the existing owner and separately verifies selection. |
| `install_revision` | The same exact bundle descriptor with strictly newer rule revision and artifact generation. Publishes one fresh native candidate linked to the previous artifact, extends signed CURRENT, independently selects it, and explicitly replaces the research consumer. Existing FinalUse and inference owners and prior request records are retained. |
| `execute` | Unique `sequence`, normalized three-role `input_state`, three-value `expected_prediction_q24`; optional exact descriptor and current `checkpoint_anchor`. The request digest binds the complete command. |
| `revoke_finaluse` | `sequence` identifies a fixture grant to durably revoke through the existing FinalUse owner. |
| `expire_selection` | Waits for actual signed selection expiry only when that wait is at most 2.5 seconds. Initialize a one-second selection for this case. |
| `corrupt_current` | Mutates the fixture head signature on disk; subsequent native discovery must reject it. |
| `restart` | Drops and reopens existing native owners using the exact retained signed CURRENT floor and original signed selection. It neither publishes nor renews selection expiry. Persisted grants and inference requests retain their refusal/reconciliation behavior, including after an explicit fresh candidate installation. |
| `status` | Reports initialization and actual durable inference journal length. |
| `quit` | Drops the process owners. |

`execute` supports bounded negative experiments: `revoke_after_claim`,
`timeout_ms` from 1 to 30,000, `driver_delay_ms` up to 1,000, `driver_fail`,
and `driver_panic`. The callback reads the exact selected payload, applies its
six-entry finite role permutation, and returns a native inference receipt.
Each actual callback entry first appends and syncs `inference-driver.jsonl`.
That trace is an observation, never authorization.

Only accepted terminal execution returns an `effect`. Refused late or uncertain
results retain raw inference observations and cost evidence without delivery.
Elapsed and callback microseconds, journal growth, and finite buffer capacities
are measured; JSON heap, process peak memory, energy and billing are not inferred.

The named artifact owner has no supported durable Revoke/Quarantine CURRENT
mutation interface. An attempted combined publication was rejected by its
one-Register transaction invariant; it is retained as failed evidence elsewhere.
The signed revoked-view native tests exercise the existing read-only verifier,
not an acknowledged mutation by that service. RuleSlot revocation and native
FinalUse revocation remain separately tested. Admission and execution responses
mark `production_qualified: false`; Four-Gate and product qualification are unchanged.
