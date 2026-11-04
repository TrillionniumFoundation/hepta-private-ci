# Cell runtime evidence

`bind_cell_evidence_v1` closes the first receipt boundary between a per-Cell
head and the existing local Neuron runtime.

It accepts a `CellHeadV1` plus its `CellHeadOutputV1` and a
`NeuronRuntimeOutputV1`. It checks:

- Cell ID and head digest binding;
- nonempty model-runtime, temporal-state, checkpoint, and action digests;
- the local runtime receipt's semantic digest;
- the runtime's bounded confidence and OOD ppm values;
- the existing non-authorizing authority posture.

The resulting `CellEvidenceV1` keeps the head action digest, runtime receipt
digest, model binding digest, confidence/OOD measurements, abstention, and
resource receipt together under one canonical evidence digest. It is suitable
as the input record for the Group NDU observation adapter. It does not grant
authority, execute a model, train a critic, or claim System2 emergence.

The model binding digest is retained from the existing runtime signal. The
adapter does not reconstruct it from incomplete output fields, which keeps the
existing runtime receipt contract intact while making the evidence dependency
explicit.
