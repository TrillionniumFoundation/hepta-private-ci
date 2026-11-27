# Parent-supervised network handoff

**Draft / HOLD / NoUpdate. Zero model calls or memory-benefit episodes.**

A socket timeout did not bound the complete network operation. The original
slow-header control took 1.820909942 seconds with a 0.25-second profile. Its raw
red output is retained, separately from later source/attempts.

The parent now syncs request admission before starting a fresh Python transport
worker, passes pinned loaded transport bytes, and enforces the network deadline.
On timeout it kills and reaps that direct worker, returns UNKNOWN and never
reissues the request. The parent alone settles the durable terminal. Worker
stdout/stderr, return status and reaping are bound into recovery evidence.
The child uses `-I -S -B`; URLs are limited to 4096 UTF-8 bytes. Changed loaded
transport source is rejected before admission.

This bounds the trusted network worker, including DNS and response-header wait.
Bounded input admission/fsync remain outside the network budget. This is not
arbitrary descendant cleanup or hostile-worker output defense; the pinned
stdlib-only worker has a closed result shape. Timeout leaves the provider's
physical outcome unknown even after the local worker has been reaped.

The final composed source passed **24/24**, zero failures/skips, with clean Git
identity before/after under the repository's 60-second supervisor. The earlier
16/22/24 case results overlap and are not summed. Actual localhost controls
verify admission before spawn, slow-header termination, reaping, no retry,
byte-exact delivery and corrupted evidence recovery.

Tested source: `b8a6feb2a2200adb7ee9b9dad556a7bc30a8acff`, tree
`7346fd47dcdc5c575c8a74772e19981947117ead`. Final repository `just fmt` passed;
both Python ASTs match tested bytes, and Ruff/diff checks passed. No tests were
repeated after formatting. Formatted source and complete original logs, failed
intermediates, postimages and identities are bound by [EVIDENCE.json](./EVIDENCE.json)
and [raw-validation.tar.xz](./raw-validation.tar.xz).

Original provider/owner authority and settlement, new-source exposure, complete
effect recovery and real causal net benefit remain unqualified. No production
adoption, original request replay, host-policy change or merge is performed.
