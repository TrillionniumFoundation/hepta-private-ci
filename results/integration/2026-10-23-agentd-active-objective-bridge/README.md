# Agentd Objective bridge: use the active original payload helper

Publication base: `5a3ffeb70afaa56c4390551f740073b68ec539e3`, tree
`7699e4f07fda871f885398aea873a01dfc05213f`.
Rust preimages are the original `db91f9ec316ba1472e7adf97f8415949de012469`
source, tree `81c03af04be56659d3eb4da71bf61aeac34c949f`. The parent's complete
readback records that the intervening commits add evidence and CI without
changing that Rust source pin. Publication must still compare the two preimage
Git blobs against the actual branch head before a CAS update.

## Defect and minimal fix

`objective_sender_host_tests.rs` called
`crate::objective_ingress::objective_payload` at two sites. `lib.rs` does not
declare that legacy module: its active implementation is `objective_runtime`.
The legacy source file's presence on disk does not make it a Rust module.

The fix reuses `objective_runtime::objective_payload`, widening its visibility
from private to `pub(crate)` without changing its signature or body. Both bridge
calls pass `config.identity().spawn_generation` to its existing third parameter.
The test continues to compare the exact canonical body bytes and SHA-256 and to
reject the empty source envelope. Its three test names and all assertions stay
in place. No legacy module is enabled, and no parallel canonicalizer is added.

The only production-source change is crate-internal helper visibility. The
existing runtime call, validation, body serialization, transport, owner,
authorization, schema, dependencies and Cargo lock are unchanged.

## Verification boundary

- Both source preimages were read from the fixed original Git checkout and their
  full bytes matched their original Git blobs and file modes.
- Static call-site checks verify the active module declaration, legacy module
  absence, unchanged original helper signature/body, two replacement calls,
  explicit generation inputs and unchanged bridge test names.
- The existing Rust 1.88 formatter parsed each complete candidate file from
  stdin using edition 2024. It exited 0 with empty stderr, and its output was
  byte-for-byte equal to each final input. This is a syntax/format comparison,
  **not** a Rust 1.95 `just fmt` gate or a Rust type-check.
- No Cargo command, original Agentd package test, CI job or GitHub write was run
  for this fix. The original owning-package gate must still compile and execute
  the full Agentd library, including the three bridge tests. The earlier memory
  322 and Desktop host 14 passes do not qualify these Agentd changes.
- The Desktop host and memory dependency pin remains `db91f9e`. This correction
  is a later Agentd-only follow-up; it does not rewrite earlier evidence.

The unchanged test command for the original workspace is
`just test --locked -p codex-hepta-agentd --lib`. This report does not claim that
command has executed. No production checkpoint or issuer is supplied by the fix.
