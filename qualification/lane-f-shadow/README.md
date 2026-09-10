# Lane F shadow qualification

This standalone crate executes the five Lane F source kernels in one deterministic
qualification-only path:

```text
neuron.runtime
-> prompt.optimizer local shadow
-> intuition.policy advisory decision
-> intelligence.control plan
-> learning.plasticity next-generation candidate set
```

It remains outside the product workspace. The standalone manifest owns a source-controlled `Cargo.lock` generated from its exact
path manifests. CI runs locked tests and lint at both the exact head and a deterministic
synthetic merge candidate.

A pass proves source-level composition, deterministic replay, bounded inputs, a
no-change candidate, an exact rollback predecessor, and
`AuthorityPosture::DENY_ALL` at every stage. It does not prove a production
caller, real-model identity, causal or future-window efficacy, independent
acceptance, canary safety, selection, promotion, merge authority, or release.
