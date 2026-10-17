# Independently selected compact Neuron Model descriptor (diagnostic only)

This profile uses the already implemented \`ArtifactSelectionVerifierV1\`
(Ed25519 selector, scoped CURRENT artifact registry and independent head-witness)
and \`load_selected_candidate\` (exact immutable selected artifact bytes).
A currently selected \`NeuronRuntime\` is **not** implied by this selection.

**Important physical size:** \`ArtifactRegistry\` limits artifact payloads to
64 MiB; the three frozen Laya checkpoints are 644–843 MB. The new
\`NeuronSelectedModelDescriptorV1\` is therefore **a small canonical JSON Model
artifact (8 KiB maximum)**, not the raw weights. Its 15 fields pin schema,
model ID, Scope, Objective, Generation and the immutable runtime model tuple
(model manifest, Encoder/Head, weights, tokenizer, preprocessor, quantization,
runtime/device, normalization, native config).

The host independently authenticates the CURRENT registry view and selector
keys before calling
\`AgentdNeuronOwner::read_model_artifact_candidate_v1(...)\`. It opens the
preexisting pinned registry snapshot and descriptor payload files as regular
File objects; this call verifies the selected manifest, revalidates the
CURRENT lineage and decodes canonical bytes. It then compares every
descriptor field with a **real locally witnessed** Neuron config/checkpoint.
A matching result carries a recomputable diagnostic digest and DENY_ALL,
not a production-selected flag. A forged payload, changed registry head,
revoked lineage, absent/changed witness or model-tuple drift is refused.

This profile deliberately does NOT load Laya weights, inspect actual runtime
CNS routing, prove a production Cell was selected, issue final-use authority,
establish an independent host attestation, or license raw observations. The
selected descriptor's weights digest is only one end of an eventual trusted
\`ArtifactLoadReceipt\` from the physical model/CAS owner. At the real use
boundary the host must re-verify the exact selected route/CNS, current
generation/fence, actual loaded bytes, independent source permissions and
any registry/selection revocation. Two separately valid owner receipts are
not an atomic cross-store transaction.

There is no second registry or new Artifact key issuer here. The producer
must first create/persist the descriptor by the existing Artifact CAS pipeline
and have it independently selected; a caller-made self-consistent JSON cannot
pass this API. Tests cover the strict codec and negative field changes; the
artifact crate's existing \`art_12\` test covers the independent CURRENT
selection signature and revoked/changed head. All true production selection,
actual future-label evaluation, NDU and resource/rollback acceptance remain
external. PR #1494 remains Draft.
