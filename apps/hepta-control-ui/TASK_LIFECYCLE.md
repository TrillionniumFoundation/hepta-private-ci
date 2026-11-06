# Chat task lifecycle and acceptance boundary

The product candidate keeps the Robrix-derived Makepad chat and its embedded
Console. Web and native renderers use `hepta-control-core`; a renderer is not a
runtime owner, credential issuer or second operation journal. This document
describes the Objective-connected candidate, not an activated deployment.

## Original owner path

A trusted native host can install `install_original_objective_ui` with an
already prepared, independently authorized original request, the original
production sender/checkpoint, a live owner session and the exact draft/window
binding. The default HTTP bundle and standalone desktop preview do not install
that host. A local draft or an available Console does not authorize dispatch.

The existing Send, Cancel and Refresh controls use that one installed port.
The port sends through the original Agentd ControlServer and stores observations
through the original Memory production writer. It creates neither a signer nor
another database. A queued command is not execution success; the draft and
timeline remain unchanged until their actual owner supplies corresponding data.

After an operation starts, one worker follows the original request. Healthy
reads are separated by one second after completion. Unknown outcomes back off
to two, four and then five seconds. A timer only requests observation; it never
reissues Submit or Cancel. There is no catch-up burst after slow I/O. An observed
terminal stops automatic reads. Closing the window or expiring its original
session ends this UI observer, without claiming that an admitted run stopped.

## Evidence and recovery

The protocol adapter compares complete authenticated responses inside the
original sender transaction. Only the per-read request correlation ID is
excluded from equivalence. Schema, agent, original and current generations and
the complete payload remain significant. Equivalent states re-acknowledge the
existing evidence; different states retain their exact original response bytes.
RunStatus receipts, including terminal receipts, are retained and independently
acknowledged before the client returns them for presentation.

The writer's current authority and checkpoint checks still apply on both paths.
The original 64-event limit is unchanged. Repeated identical status reads no
longer consume it; distinct transitions still do. This is bounded task-status
observation, not a message/usage streaming log or unlimited history service.

Reopening a UI/client can query its original request and acknowledged evidence.
It cannot acquire a fresh sending permission from recovered state. Unknown
submission or cancellation results are reconciled by observation, not replay.
Client recovery tests do not prove Agentd/App Server dual-process recovery.

## What product acceptance still requires

| Area | Required observation |
| --- | --- |
| Ordinary entry | The actual Web, desktop or device entry authenticates the principal and attaches the existing owner without a test-only installer. |
| Objective and progress | A user-issued task retains the draft/request binding and shows actual admission, context, dispatch and TaskFlow progress. The current Objective view still groups several nonterminal phases together. |
| Memory | Real context acquisition, source scope and any intended memory effect are bound to that task and its current authority. |
| Effects and terminal | The intended provider/tool/device effect is independently read back and matches the durable terminal and audit evidence. A status label alone is insufficient. |
| Cancellation | Before/after dispatch, lost ACK, disconnect and permission revocation preserve unknown outcomes and do not duplicate effects. |
| Recovery | The same request survives the required process/host restart scenarios, preserving terminal, effect and usage reconciliation. |
| Cross-surface state | Room, window, principal and generation fences survive navigation, multi-window focus changes and reconnection. |
| Platform input | Chromium and browser bridges, physical IME/CJK, accessibility and mobile touch pass on their actual supported environments. |
| Resources | Idle and active CPU/RSS, observer traffic, checkpoint writes and shutdown cleanup are measured for the fixed source and deployment. |

The regression fixtures exercise the real ControlServer, SQLite sender and
ChatWorkspace, but their external provider/device effect count is zero. They
qualify those protocol and recovery boundaries only. Static captures, presenter
tests and a green browser suite do not close the product conditions above.

## Reproduction

Use the repository's pinned toolchain and original test runner from the root:

```sh
just test --manifest-path ../apps/hepta-control-ui/rust/Cargo.toml \
  -p hepta-control-core -p hepta-robrix-ui --no-default-features --lib
just test -p codex-hepta-agentd --features desktop-objective-ui --lib \
  -E 'test(objective_control) | test(desktop_objective_ui) | test(objective_sender)'
just test -p codex-hepta-memory --lib -E 'test(objective_sender)'
```

The existing `ui-product-foundation.yml` retains its source and merge lanes,
strict browser pins, capture requirements, semantic checks and native platform
scope. Results remain bound to the exact executed source and environment.
