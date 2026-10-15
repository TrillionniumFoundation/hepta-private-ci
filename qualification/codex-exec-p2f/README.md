# P2f: actual Codex wire -> original Evidence cold recovery -> no-effect entry

This is a test-only child of P2e PR #2259 at exact commit
c8b559d09141c331ca27096fda93a079d62677d9 (which stacks on P2d
#2150 at a2d9d5ef229e5dc2ea3baee4e60195b40b3ff056).

P2e checks real JSONRPC/ExecParams types against pinned upstream; P2f
crosses a different qualification boundary: the original Hepta
codex-hepta-evidence::HeptaEvidenceStore persists the **same exact physical
process/start request digest** inside its typed non-effect envelope, is closed,
and is reopened read-only. recover_execution_preparation_by_key_v1 reconstructs
the envelope solely from the durable original provider key; afterward the
original audit_execution_effect_entry_denied_v1 **must deny** physical tool
entry. Modified raw wire and stale fence fail closed. Quarantined indeterminate
records still require original-owner reconciliation after cold reopen.
All 44 unadmitted corpus examples must be rejected before test-only
Evidence composition.

The test uses the exact frozen P2e corpus: 6 accepted inspection examples and
44 rejected examples are expected counts, NOT yet new Rust pass results.
Cases exercise original durable SQLite, not an in-memory substitute. The
integration test has three registered Rust tests, not 50 separate tests.

No new production source, dependency, migration, signer, owner, network caller,
tool dispatch, authorization, replay or retry path is introduced. This is a
test-only composition; it does NOT make P2c preflight mandatory in the real
production entry route. Correct Evidence rejection does not prove an outside
process never performed a physical effect. Testing an indeterminate bookkeeping
record is not a physical crash/power-loss experiment.

The exact source-head and prospective-base native workflow
.github/workflows/hepta-exec-p2f.yml covers original Evidence owner tests,
P2c contracts, locked Cargo, native Rustfmt, strict Clippy and clean-tree
checks. Parent P2e native source-head and base-merge tests must also pass.

Future owner work still requires an independent signed Final-use verified at
the real provider entry, scope/generation/fence/nonce/expiry/revocation,
runtime executable and sandbox/environment/network custody, pending-before-
effect journal and durable terminal reconciliation, target-host power-loss
testing, performance evidence and all blocking-ci gates.

**DRAFT / DENY_ALL / NO PHYSICAL TOOL / NO PRODUCTION MERGE.**
