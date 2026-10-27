# Completed cumulative-control diagnostic

Run [40501186161](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40501186161)
tested source `6ba1a5b352568250edcec5975972d7d67d30e295`, tree
`1e6cc38a6f1bb78ce78a01049dfd1066d11e3a65`. Its required outcome was **success**
and its campaign status was `completed-diagnostic-no-installation`.

The original candidate and round-one controls came from source `f75bf1ac`.
Actual cumulative LoRA and full-tune continuations added the original ten-step
plan twice, preserving each real parent checkpoint, per-role learning rate and
per-round AdamW reset. Candidate and controls have cumulative steps 10/20/30,
input tokens 526/1052/1578 and supervised tokens 40/80/120. All three candidates
and both cumulative controls scored `1/2` in each calibration/evaluation round:
the candidate margin over the strongest cumulative control was zero throughout.

The original 117,865,750-byte records ZIP, SHA-256
`9e9ff51116ad1e6b51500212f4fb57e0bfd6911f4833b14613a1ecd03609d05c`, is reproduced
exactly by this recipe and its pinned ci008 base. All 11,544 retained members,
including both indices, were verified. The separate 1,620,808,534-byte checkpoint
ZIP is identified in the manifest; its bytes were not downloaded locally and
the ten omitted `.safetensors` members are not reconstructed by this increment.

See [the restoration procedure and limits](../INCREMENTAL_RECORDS.md).
This is a matched cumulative step/token diagnostic, with zero installed children
and no SystemLongitudinal qualification, independent future-quality proof or
equal time/FLOPs/economic-cost claim. The original failed ordinary gate and
original six-arm results remain unchanged.
