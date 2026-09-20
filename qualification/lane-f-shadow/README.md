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

It remains outside the product workspace. The workflow derives a temporary lock
from the exact `codex-rs/Cargo.lock`, adds only this harness root package, runs
locked tests/lint, and removes the temporary file before the clean-tree check.

A pass proves source-level composition, deterministic replay, bounded inputs, a
no-change candidate, an exact rollback predecessor, and
`AuthorityPosture::DENY_ALL` at every stage. It does not prove a production
caller, real-model identity, causal or future-window efficacy, independent
acceptance, canary safety, selection, promotion, merge authority, or release.
