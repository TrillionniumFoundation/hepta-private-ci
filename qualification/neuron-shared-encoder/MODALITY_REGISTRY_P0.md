# Frozen modality registry — research-only P0

This tranche adds the identity boundary between a shared Stem and the
modality-specific towers/projectors described by the Stem/Cell contracts.

## Scope

modality_registry.py defines:

- ModalityTowerSpecV1: one frozen, source-bound text/image/audio/video tower;
- ProjectorSpecV1: one source-bound projector into the shared Stem width;
- ModalityTowerRegistryV1: a generation-fenced immutable tower registry;
- ProjectorRegistryV1: a generation-fenced immutable projector registry;
- BoundModalityRegistriesV1: a non-authorizing binding of both registries to one
  StemManifestV1;
- registry_manifest: a deterministic manifest suitable for a qualification
  receipt.

The registry binds tower and preprocessor digests, hidden widths, quantization,
streaming/temporal/region capabilities, projector kind, slot budget, zero-gate
initialization and source-bound status. It does not load a checkpoint, run a
forward pass, train a projector, align modalities, choose a Stem, or activate a
decoder.

## Contract invariants

1. Every tower is frozen and source-bound.
2. Audio and video towers declare temporal support.
3. Image towers declare region support.
4. Every projector is source-bound and zero-gate initialized.
5. Every projector output width equals the shared Stem width.
6. Tower output width equals its modality projector input width.
7. Tower/projector modality sets are identical.
8. The projector ID must already be registered by StemManifestV1.
9. Registry digests are deterministic and generation scoped.
10. All bindings remain DENY_ALL; registry creation is not model selection or
    production admission.

## Relationship to the existing bridge

ModalityEnvelopeV1 remains the input envelope for source-bound projected
features. This registry adds the missing producer identity: the envelope's
projector_digest can now be resolved against a frozen projector registry, and
the registry can be included in a QualificationReceiptV1 through its
deterministic manifest.

The next real qualification step is still a blinded, independently held,
source-disjoint transfer run for each modality. Registry tests are protocol
tests only. They do not demonstrate image/audio/video pretrained forward
quality, semantic alignment, generation, latency, or Cell efficacy.

## Validation

~~~
python3 -m py_compile \
  qualification/neuron-shared-encoder/neuron_shared_encoder/modality_registry.py \
  qualification/neuron-shared-encoder/test_modality_registry.py

python3 qualification/neuron-shared-encoder/test_modality_registry.py
# Ran 10 tests — OK
~~~

The change remains research-only, shadow-only and non-authorizing. It does not
change main, model selection, final-use authority, decoder execution, or
production behavior.
