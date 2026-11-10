# CTRL text identity observations

2026-11-09. HOLD / no-update. Base: #5450 at
f6a7d5307f888d30faa8803d23487c78789b99fe.

The six zero-quality WRITE_TEXT observations cannot be attributed to a specific
selection/delivery fault from the public aggregate. Original V2 training rows
omit selected indices and delivered payloads. This change adds future observations
without changing the candidate selector or controller.

For WRITE_TEXT the actor records the candidate index, candidate/set identities,
text-byte identity and serialized action identity. The host checks available
candidate metadata and action identity. After actor exit it compares the action
text with the delivery snapshot and binds that snapshot to the separate scorer's
existing delivery digest. WRITE_TEXT followed by STOP and repeated writes bind
the latest preceding write to the final scored snapshot.

Recorded-candidate verification, actor-only declarations and absent historical
selection remain distinct. Actor declarations never become verified selection.
Full byte continuity can accompany zero semantic quality. Hashes do not prove
the model computed its logits or authenticate a native owner. Low-entropy text
digests must remain private; they are not anonymization. A new run must regenerate
its source inventory, retaining all old pins and registrations.

Validation: 12/12 protocol tests passed, zero skips. Six direct tests distinguish
wrong selection, changed serialization/candidate, replacement during delivery,
scorer input mismatch, historical unknown selection and case mismatch. Six
integration tests execute actual make_action/snapshot/score method bodies using
AST isolation and a separate fixture scorer subprocess. They include terminal
STOP and repeated WRITE. They do not run Torch inference, OCR, native owner
authentication or a real policy-benefit experiment.

```sh
PYTHONPATH=scripts python -m unittest ndu_real_runtime.test_content_identity ndu_real_runtime.test_content_identity_integration -v
```

No original record, reference, weight, registration or score is rewritten.
#5451 remains a sibling with its existing dynamic fallback. Promotion still
requires real complete-cost gains over strong baselines on independent tasks.
