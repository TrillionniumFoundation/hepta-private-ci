# Legacy Windows workspace isolation is unavailable

The legacy same-user backend rejects isolated-workspace requests before preparing the sandbox or starting a process. Callers must return the refusal, not retry outside a sandbox.

The maintained contract is in `src/legacy_admission.rs`; its native tests cover token creation, preflight, capture, and spawn preparation.
