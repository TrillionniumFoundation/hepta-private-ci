# External Cell Split effect-owner RPC (source contract, not production qualification)

This is the deployment protocol for the four **separate** owners behind
`CellSplitUnixPortV1` and `CellSplitExecutionOwnerV1`. The coordinator
only serializes a frozen plan, issues write-ahead intents, authenticates signed
results and re-queries the exact effect owner. A port returning success does
not confer CNS, Supervisor, NDU, selector or physical-split authority.

## Socket and wire boundary

- Four unique owner IDs, socket paths and Ed25519 verifying keys; a single
  operator-controlled private canonical directory and direct-child Unix
  sockets. The client checks for socket path substitution before/after connect.
- A request is a four-byte unsigned **big-endian** JSON length, followed by
  canonical JSON (sorted object keys and no trailing bytes in the frame).
  The maximum request/response body is 128 KiB and the per-I/O deadline is
  five seconds. One connection carries one request and one response.
- Request fields: `schema`, `operation`, `intent`, `plan`.
  Schema: `hepta.learning.cell-split.external-effect-rpc.v1`.
  Operations: `execute`, `read_committed`.
- Response fields: `schema`, `operation`, `intent`, `ownerId`,
  `receipt`, `failure`. Exactly one of `receipt` and `failure`
  can be present on successful `execute`; `read_committed` may return
  `receipt: null` only if the committed effect is genuinely absent.
- Every server must recompute the canonical `planDigest` from the full
  `plan`, verify `ownerId`, `step`, preconditions and
  `idempotencyKey` against its own durable state, enforce authorization
  before effects and reject unknown schema or fields. The RPC client
  independently rejects mismatched plan, owner, operation and response
  identities. The coordinator verifies the independently pinned signature.

## Domain responsibilities

| Step | Only the real owner may execute | Required read-back |
| --- | --- | --- |
| 0 Artifact CAS | Commit child model bytes under immutable content address, fsync data and directory, and publish CAS metadata | Exact materialization identity, byte digest, generation and durable CAS receipt |
| 1 Child state migration | Apply registered parent-to-child transform from a committed parent checkpoint; persist child state and child-bootstrap readiness | Durable child snapshot, parent anchor, transform and readiness receipt |
| 2 CNS route cutover | Atomically publish the admitted route/revision with predecessor fence; never reuse retired generation identity | Current route, successor binding, predecessor fence and publication sequence |
| 3 Supervisor generation fence | Complete old-generation drain/retirement and install the admitted successor generation under current authority | Committed generation/authority/fence state; old results and routes still denied |

The server must return the **original domain receipt bytes**, operation
sequence and a distinct owner signature. The signature payload is generated
with `cell_split_execution_signing_payload_v1`. It covers the immutable
intent, owner sequence, output digest and raw receipt bytes. An opaque digest
statement or an RPC echo of the request is not proof of the effect.

**Crash protocol:** persist the domain operation under the idempotency key
before answering `execute`. After a lost acknowledgement or timeout, the
coordinator must only use `read_committed`; it must never replay
`execute`. The read method must inspect the authoritative durable domain
record or recover the exact original committed receipt. It cannot create an
effect, return a guessed digest, substitute a new signature, or turn missing
durability into a success. If the effect is absent or indeterminate, the split
stays fenced pending out-of-band reconciliation.

## Additional production gates

Before this RPC is used for production, Agentd must bind it to authenticated
NDU no-change-baseline evaluation and an independent Selector; each of the
four owning services must run an actual implementation of the table above,
not a test listener. Reopen, crash-after-commit, lost ACK, rollback/tombstone,
CNS generation fencing and power-loss recovery must be tested under the
deployment's authenticated host and independent observers.

The target-host signed 16-case evidence gate lives separately in
`qualification/physical-split/` on PR #1487. Neither the successful socket
unit tests nor the source-level coordinator permits physical splitting.
