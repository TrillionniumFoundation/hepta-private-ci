# P2c — Codex Exec Server physical-request method preflight

Status: **RESEARCH_ONLY / DENY_ALL / no deployment or effect entry**.

This branch stacks on [P2b #1993](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1993), not on main. P1 and P2a are still not independently qualified as of the source freeze. P2c has no process launcher, no WebSocket, no app-server client, no Final-use issuer, no execution queue, no writer, and no callable provider dispatch.

## Why this additional typed gate?

The upstream [Codex 0.162.1 release](https://github.com/openai/codex/releases/tag/rust-v0.162.1), particularly [exec-server protocol](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/exec-server-protocol/src/protocol.rs) and [Exec Server README](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/exec-server/README.md), exposes process/start, process/write, process/terminate, fs/remove, fs/writeFile, http/request, etc. They have different external effects. A general Exec Server transport connection must not be mistaken for a grant covering all these methods. Exec Server uses a JSON-RPC dialect without the JSON-RPC "2.0" field.

This P2c source limits one future candidate profile to a single **process/start** request and a fixed destination string. The request must match its original P1 physical SHA-256 digest/length, use the original operation ID for both JSON-RPC id and processId, reject unknown/duplicate/missing critical fields, and require non-interactive settings: tty=false, pipeStdin=false, arg0=null/absent, env={} and a file:/// cwd string. It bounds argv, frame size and path length. It does **not** validate real file system custody, symlinks or process policy; those remain with the trusted physical sandbox owner. No claim is made that arbitrary shell commands are safe.

A successful preflight result contains only digests, the operation ID, argv count and method label. It is **not** an authority token, not independently signed evidence, not an execution callback and not a guarantee that a real Codex release accepts the request. This is a narrow syntax/correlation preflight rather than full upstream protocol qualification.

## Native tests and evidence expectations

Run on the exact committed source and prospective merge with P2b:

```sh
cd codex-rs
cargo fmt -p codex-hepta-contracts -- --check
cargo check --locked -p codex-hepta-contracts --all-targets
cargo test --locked -p codex-hepta-contracts --lib exec_server_start_p2c
cargo clippy --locked -p codex-hepta-contracts --all-targets -- -D warnings
```

Twelve unit tests cover: legitimate synthetic schema readback, model-only confusion, cross-destination confusion, unrelated Exec Server methods, dual operation/process IDs, byte tamper, JSON-RPC dialect/duplicate and unknown fields, RPC response/notification substitution, process interactivity and environment escalation, malformed/oversized argv and wire, and request-byte-order changes.

All tests remain source-only until native exact-HEAD CI actually completes. Even passing them cannot turn the P2b deny-only port into a production caller. No Codex process, model, FileUse, shell, real filesystem effects, durable physical outbox or Final-use signing occurs.

## Mandatory next owner-side sequence

The original Agentd/Operations owner must authenticate selected caller and purpose, re-check current generation/fence/authority epoch/time/deletion/revocation, persist exact **physical** request before effect, obtain and verify a separately issued single-use Final-use token for that exact tool payload, enter with the original authority API at the irreversible boundary, perform the real upstream process/start through its sandboxed Exec Server connection, and reconcile the same operation by original provider status after unknown response. Every mutation-capable later RPC (e.g. process/write, fs/remove) requires a **different** explicit effect intent, authorization and recovery policy. Only after those production owners are independently qualified can true performance comparisons run.

A request digest is an identity check, not permission; no model turn/start or Cell output can mint a tool-execution capability. Never imply unverified provider status is terminal success. No automatic retry of a lost command acknowledgment.
