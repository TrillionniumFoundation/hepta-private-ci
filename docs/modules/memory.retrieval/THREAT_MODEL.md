# Retrieval threat model

## Assets and assumptions

Protect private memory contents, exact record provenance, current generation identity, context delivery correctness, rollout identity, bounded host resources and trustworthy qualification claims. SQLite and the learning ledger remain separate durable owners. Context-signing and frontier-signing keys plus rollout descriptor/digest are startup inputs supplied through protected host composition, not request parameters. A hostile local process may occupy the loopback endpoint; endpoint locality is not authentication.

The frontier owner must retain its epoch/sequence outside the Agent home's rollback domain. The checked-in client does not implement or qualify that external persistence. A fresh challenge defeats replay of a captured response; it does not stop an authorized signer from signing rolled-back state after its own unsafe restore.

## Threats and controls

| Threat | Candidate control | Remaining proof |
| --- | --- | --- |
| Forged/recomputed receipt | Structural validation, generation binding; signed context/frontier at host boundary | Generator provenance still depends on the trusted owner composition. |
| Captured frontier replay | Fresh OS challenge, owner/body identity, strict Ed25519 verification and lease | Independently qualify external signer persistence and key rotation. |
| Same-sequence substitution | In-process monotonic floor rejects digest drift | Restored/replaced frontier service needs an external monotonic witness. |
| Request-selected treatment arm | Host wrapper owns mode; bootstrap v2 policy is descriptor-pinned and captured once; requests cannot supply threshold or salt | Qualify launcher ownership and server-side policy-change approval. |
| Cohort reshuffle during upgrade | Bootstrap v1 preserves the original cohort algorithm exactly; v2 uses an explicit version and generation salt | Independently approve cohort continuity or intentional salt rotation. |
| Shadow resource amplification | Descriptor-pinned candidate/node/synapse/step ceilings checked before non-delivery HNMF | Add measured CPU, RSS, allocation, wall-time, cancellation and scheduler isolation. |
| Slow/oversized endpoint | Explicit loopback address, one total 10 ms–5 s deadline, 4 KiB frame cap | Measure scheduler and transport behavior on the approved host. |
| Unknown or ambiguous wire fields | Strict JSON fields, duplicate rejection and lowercase fixed-length hex; v1 rejects v2 fields and v2 requires all fields | No version downgrade or undocumented translation is allowed. |
| Candidate poisoning | Positive-score policy admission before OOD/conflict/dynamics | Admitted adversarial evidence still needs owner authentication and calibrated risk policy. |
| False contradictions | Proposition/generation/polarity binding; conflict reports are not denials | Owners must provide canonical proposition/time identity. |
| Phantom graph support | Strict-positive activation and zero-weight-edge neutrality | Execute semantic and property-grid tests on the exact source. |
| TOCTOU deletion/correction | Exact cut/revision/hash admission and final owner/source/retrieval-policy revalidation | Exercise races and restore/restart on the named product host. |
| Learning evidence inflation | Selected and delivered sets are distinct | Delivery is not native-start/use/outcome proof; learning/eval must join those receipts. |
| Qualification laundering | Exact-object checks, nonzero test counts, independent human promotion guard | No self-approval, draft promotion, expired artifact or standalone probe can grant release. |

## Fail-closed behavior

Invalid signature, wrong owner/body/challenge, weak key, expired publication, revoked frontier, rollback, same-sequence drift, wall-clock rollback, malformed rollout policy or poisoned provider lock closes required and selected-canary HNMF delivery. The loopback client does not retry indefinitely. Its errors do not include raw memory or the received payload. Loss of optional shadow work or an over-budget non-delivery context preserves the separately defined compatibility result and is never treatment exposure. Loss of a ranker/provider must not invalidate unrelated SQLite ports.

Static shadow ceilings are not a sandbox. An allowed context can still consume substantial CPU or memory within those limits, and synchronous work can contend with baseline delivery. Activation requires separate executor/cancellation/resource accounting and target-host evidence.

No production code should synthesize a generation, all-clear OOD score, signing key, receipt, rollout salt or threshold to pass a gate. A missing Vector owner remains missing. Root/admin compromise of the repository, protected descriptor path or frontier authority is outside what a hash, PR approval or local cache can prevent.
