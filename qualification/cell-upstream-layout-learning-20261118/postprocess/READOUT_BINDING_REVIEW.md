# B3 common-prefix timing admission

Before either arm was evaluated, source review found that the readout checked release timing for B3 current-policy calls but did not repeat that check for new common-prefix calls. The readout now checks both. This changes no model, task, training source, inference request, verifier or score.

The revised readout SHA is `997feb483dc25dd4e5a138f29cd5ef07d386794c00a02b8eedd5eedaffa8ebd7`. Its original version (`71370d3c4aec806f857b59e8f32ebab50cf031f99a80777ee6730ffae785ebfe`) and checks remain in the prior commit and archive. Explicit Ruff format check and lint both exited zero; no B3 materials, models or verifiers were accessed by this preparation.
