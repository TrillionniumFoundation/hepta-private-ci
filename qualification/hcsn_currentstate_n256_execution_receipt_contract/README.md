# N256 execution receipt contract — HOLD

The frozen admission/execution bridge binds a future provider admission, atomic
execution freeze, and three-stream manifest, but the manifest itself carries no
immutable proof that the exact key, host, and capture session completed inside
the frozen execution interval.

This source-only stage adds that missing fail-closed boundary. A future receipt
must bind the admission, freeze, canonical manifest bytes, execution key, host,
capture session, start/completion timestamps, successful exit, and preservation
of historical RED/UNKNOWN. It cannot self-grant qualification or production
adoption.

Synthetic fixtures test parser and cross-binding behavior only. They do not
supply any of the ten future originals, allocate a key, execute N256 numerics,
call the provider, or create an authentic receipt.

Status: **HOLD / NoUpdate / all_closed=false**.

## Receipt exit type repair

The receipt validator requires an integer process exit code. Python considers
`false` and `0.0` equal to integer zero, so a success comparison alone previously
accepted either value in a correctly rehashed receipt. The publisher's earlier
integer check did not protect callers that validate persisted receipts directly.
The repaired contract rejects these values before the success comparison, and
regressions exercise both direct receipt validation and terminal publication
validation after recomputing every affected digest.

The exact pre-repair source, tests, source freeze, and downstream verifier pins
are preserved under `qualification/hcsn_receipt_type_original_9fd4f17/` with byte
hashes and Git blob identities. The current source freeze identifies this repair
separately. No authentic receipt, execution fact, or scientific qualification is
created by these synthetic checks.
