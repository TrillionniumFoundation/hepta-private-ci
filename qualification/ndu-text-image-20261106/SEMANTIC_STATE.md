# Addressable text/image state for the next NDU experiment

This additive package fixes a specific representation limit in the existing V3
controller: `slots.mean(1)` is identical when the text and image contents are
swapped. The new profile keeps named slots and their observable work state. It
does not reclassify earlier synthetic mechanisms as natural semantic evidence.

## Common state for all four arms

`ndu_semantic_state.state.from_public_encodings` takes a shared `[batch, width]`
array, exactly two named encodings, and public metadata. Both ordinary/Hepta
cores and both light/NDU controllers use the same `3 * width + 20` features.
There is no arm label argument. The stable order is shared content, text
encoding and metadata, image encoding and metadata, then budget/time.

Each slot carries availability, progress in `[0,1]`, preparation
(`not_required`, `pending`, `ready`), content version and committed prefix
receipt. Versions, availability, preparation and progress remain distinct.
Availability means a valid current slot, not a delivered answer or good quality.
Missing slots must have zero encoding/progress/version and an empty prefix.
Direct dataclass construction and replacement enforce the same invariants,
including the text/image slot order. Arrays are copied onto immutable byte
storage; callers cannot re-enable writes to alter a validated snapshot.
Extra fields such as targets, future observations, evaluator scores and arm
labels are rejected at every structured input boundary. The schema cannot
detect leakage already hidden inside an arbitrary caller-supplied numeric
vector; the bound encoder, material roles and independent observer still matter.

The `representation` field is explicit and enters the actor binding:

| Representation | Meaning |
| --- | --- |
| `public_output_encoding` | A registered encoder's representation of current public output |
| `joint_content_latent` | Differentiable internal text/image content; it does not imply output bytes or delivery |
| `legacy_v3_latent` | Explicitly migrated old V3 slot values; previous semantic qualification is not inherited |

`actor_binding(state)` binds names, order, width, representation and schema.
`check_actor_binding` rejects old V3 actor metadata and representations that do
not match. A binding is an input-layout contract, not proof that weights were
trained honestly; the checkpoint bytes remain separately pinned.

`migrate_v3_latents` accepts the V3 `[image,audio,video,text]` tensor, preserving
text/image values and hashing the original input dtypes, shapes and bytes. It
returns an explicit migration receipt stating that the old actor is incompatible
and no semantic qualification is migrated. Audio/video remain in the original
checkpoint, outside this first text/image profile.

`check_transition` checks monotone time, budget and content versions. Changed
content requires a new version. A changed committed-prefix receipt requires the
actual old and new bytes, matched against both hashes, to prove an append-only
extension. Equal-length rewrites, truncation and receipt rebinding fail. The
checker also validates supplied witnesses when the receipt itself is unchanged.
It performs no writes and supplies no owner authority or fabricated owner
receipt. An internal-latent experiment uses canonical empty prefixes.

## Autograd boundary

`torch_adapter.features_torch(shared, encodings, snapshot, binding)` uses the
original Torch tensors in its returned feature vector. NumPy snapshots are used
only for equality/shape validation. Content, encoders and shared state retain
their gradients. Torch is imported only when this optional helper is called.

`encode_public_outputs_torch` passes only the actual text/image output tensors to
the supplied encoders and returns the features, validated snapshot and binding.
For an internal-content probe, call `from_public_encodings` with
`representation="joint_content_latent"`, then `features_torch` directly.

The helper does not make discrete sampled token IDs or UTF-8/image codecs
differentiable. A differentiable text representation or the existing emission
likelihood-score estimator is required. Decoder loss and backward execution
must be measured against the actual frozen content model; nonzero gradients
alone establish no semantic benefit.

The smallest existing Hepta dependency is
`experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py`.
It imports only Torch and defines `HeptaCore`, including the analytic kernel.
Its `initial_state(content=encoder_tensor)` and `step` retain autograd. The
`ordinary` and `dual` modes have the same parameter shapes. To reuse the old
small dense generator, add parent `model.py` and `v3/model.py`; these retain the
old 16x16 and ontology-head limitations and are not a natural VLM replacement.
Do not reuse `v3/training.py` unchanged for a real task: it directly imports the
synthetic `mechanism_data.batch` function.

## Material integrity and source-role admission

`materials.validate_materials(root, manifest_path, registry_path,
expected_registry_sha256=OWNER_PIN, stage="development")` validates a closed
manifest against a separately pinned source-use registry. The pin must be
supplied from the existing owner/acquisition record, not copied from an incoming
manifest as a new trust decision.

Manifest schema `hepta.text-image-materials.v1` has exactly:

```
schema, experiment_id, registry_sha256, cases, models
```

Each case has `id`, `source_id`, `source_family`, `split`, `task_family`, and
`text`, `image`, `reference`, `source_evidence` file bindings. A binding contains
only `path`, `sha256`, `bytes`. Paths are canonical relative regular files;
directory-descriptor reads reject symlink components and traversal. Nonblocking
open followed by a regular-file check rejects FIFOs without waiting. Text must
be nonempty valid UTF-8; image bytes must decode as a bounded, single-frame
PNG/JPEG/WEBP image. All hashes and sizes, including separate references and
source evidence, are checked. Model files are streamed and not loaded into RAM.

Source registry schema `hepta.source-use-registry.v2` has `schema`, `sources`.
Each row binds `source_id`, `source_family`, `allowed_split`, `text_sha256s`,
`image_sha256s`, `source_evidence_sha256`, `used_in_training`,
`previously_observed`, and `case_bindings`. Each case binding fixes `case_id`,
`task_family`, `text_sha256`, `image_sha256`, and `reference_sha256` together.
Current cases must match their externally pinned owner binding; changing a
reference or recombining otherwise approved texts/images is rejected. Historical
sources may have empty case bindings but still participate in role checks.
The older v1 registry is explicitly rejected; it requires owner re-registration.
The source's original split cannot change. A consumed
source cannot become fresh confirmation; identical image bytes cannot cross
splits using different source IDs, including historical sources absent from the
current manifest. Source-family overlaps are reported, and are
not reinterpreted as independent confirmation.

Train and development must include every registered task family:

- `text_sufficient`
- `text_image_complementary`
- `selective_refinement`
- `preparation_required`
- `continuation_not_worthwhile`

The old-capability `retention` split is mandatory. Confirmation mode additionally
requires all five families in an unconsumed `confirmation` split. Family labels
are declared annotations; the validator does not infer their truth from pixels.

Each model has `id`, `role`, `architecture`, nonempty `weights` bindings, `config`,
`executable`, and a declared `parameter_count`. Bindings for text/image encoders,
text/image decoders and ordinary/Hepta cores are required. Counts and execution
are not proven by hashing bytes. The independent fairness/run gate must verify
actual loaded parameter counts and executable behavior.

Successful checks return `integrity_status="VERIFIED"` and
`research_status="HOLD"`, with `scientific_admission=false` and
`model_execution_verified=false`. A self-asserted `real=true` field is rejected.
Even a decoded synthetic image and arbitrary hashed weight bytes cannot obtain
semantic qualification. `load_public_case` returns only UTF-8 text and RGB
pixels; hidden references, source roles and task-family labels are not exposed
as policy inputs.

## Validation

From this directory:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

NumPy and Pillow are required; Torch is optional. The Torch tests must be
executed in an environment with Torch before claiming the helper's autograd
qualification. Skips remain explicit. Tests use only temporary, explicitly
synthetic contract fixtures and start no research training or external model
request. They do not consume a reserved confirmation source.
