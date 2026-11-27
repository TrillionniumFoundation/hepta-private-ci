# Read-only peer source review

Reviewer: `/root/learn_model_carrier`; reviewed the two v4 production readback files before publication. This is a source review, with no native execution.

The new first-read methods consume `self`; request 1 uses the same fixed readonly purpose. After actual exchange they require the request echo, original pidfd/lifetime, complete D/context validity windows, and decoded signed response. Private `bind_completed` repeats fresh validation and consumes the same peer. `ReadFromOriginal` continues at request 2, while the pre-existing `PinnedBeforeRead` path retains request 1. Await, parse, and validation failure drop the original connection; no recovery branch was observed. Subsequent readers still request the original peer and use full T/S values as comparison pins. The review found no cached receipt replacing CURRENT and no reset of the original deadline or nonce.

Limit: client source structure alone does not prove original custody or Ready-only server behavior. The changed real-file mechanisms still require native execution on the final integrated source. No ordinary task or daemon restart was run.
