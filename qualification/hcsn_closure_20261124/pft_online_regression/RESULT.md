# PFT regression gate: local first rehearsal

The prospective protocol was registered at
`3962c3a3aee84748446db4023fbea47cfcdf7d26`. The driver and workflow were frozen
before execution, with the explicit runtime-closure boundary added at
`a2d8f9c794bebb0e6b4d085fa2b07babc33c550d` before the first invocation.

The new driver's single local rehearsal passed all 17 explicit synthetic
controls: LedgerTests 4, CodecTests 5, PeerTests 4 and BinaryPeerTests 4.
There were no failures, errors or skips. Exact local HEAD, clean checkout and
source hashes passed both before/after checks. Inner wall was 7.706859179
seconds; the outer supervisor observed 7.955723050 seconds, exit 0 and no timeout.

This was a local dependency capsule at actual Git head
`d78ba65ed68e3517f8090ec39e1ca669b43b2d62`, with Python 3.12.14 / NumPy 2.3.5.
It is not a full repository checkout or a hosted Actions execution. The
workflow's separately declared hosted target is Python 3.12.3 / NumPy 2.3.5
on Ubuntu 24.04, using the existing pinned repository actions.
`FROZEN.json` explicitly records `github_actions=false` and
`runtime_closure_complete=false` for the local rehearsal.

The archive `local-attempt-1.tar.gz` contains 31 files: frozen sources,
workflow/protocol bytes, actual local-head metadata, runtime observations,
all suite logs/results and child records, supervisor, formatted driver and
format evidence. Its 39,011 bytes have SHA-256
`b847c38ec02dd54162310073e9e6e3c49049fc20f25b82c139f0a96840119e07`.
Official just fmt and Ruff 0.15.13 completed after execution. The changed
driver AST is identical; all ten listed PFT implementation/test files passed
Ruff's format check. The local suite was not repeated after formatting.

The workflow uses contents:read, an exact event-head checkout without persisted
credentials, exclusive evidence outside the checkout, fixed class/count
allowlists, a 120-second test cap and failure artifact upload. Formatting uses
the exact event comparison commit after tests, with no subsequent test rerun.

No original cache, historical science budget, DEV/final data or user trace was
used. No branch protection or merge is enacted. Hosted workflow results are
separate evidence and must not be inferred from this local pass.
