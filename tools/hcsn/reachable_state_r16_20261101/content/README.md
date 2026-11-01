# R16 synthetic learned content binding

This independent content experiment establishes a shared trainable key binding
interface before attributing content performance to a dynamical core. It does
not use an HX core, prove open-domain semantics, or train a modern GRU/SSM.

The owner creates two noisy linear views of compositional categorical keys.
Only paired training views supervise the learned modality-B-to-A map. All
confirmation keys are absent from encoder training and candidate selection.
Query events contain features and elapsed time, never canonical key ids,
correct addresses or target contents. Three ordinary models share the encoder:
nearest-key slot retrieval, ridge slot retrieval, and a gated delta associative
recurrence. The exact-address oracle is separately identified as privileged.

Each episode contains eight bounded slots, 24 queries, repeated queries, five
changed overwrites and typed distractors. Content changes only through public
writes. Distractors are explicitly labelled and easy to ignore; unknown-event
classification and latent content drift remain outside this profile. Fees are
shared mandatory WRITE/QUERY charges, with measured CPU reported separately.

`PROTOCOL.json` fixes all seeds, key splits, candidate grids, domains, statistics
and the three-domain .90 accuracy gate. A negative result must retain every
domain and arm; choosing a better confirmation arm cannot rescue the gate.

Run from the repository root, with source and model publication SHAs supplied
only after those objects have been published and read back:

```sh
python -m tools.hcsn.reachable_state_r16_20261101.content.test_contract
python -m tools.hcsn.reachable_state_r16_20261101.content.campaign development --output content_dev
python -m tools.hcsn.reachable_state_r16_20261101.content.campaign train --source-commit SOURCE_SHA --output content_train
python -m tools.hcsn.reachable_state_r16_20261101.content.campaign confirm --source-commit SOURCE_SHA --model-commit MODEL_SHA --frozen content_train/FROZEN_MODELS.json --output content_confirm
```

Source/model hashes are checked before confirmation; output directories must be
new. Imported-library startup, final summary serialization, energy, process RSS,
network and production recovery are not silently inferred from inner timers.
An outer process receipt is required to extend the measured CPU account.
