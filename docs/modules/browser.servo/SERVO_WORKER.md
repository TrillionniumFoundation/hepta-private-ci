# browser.servo isolated worker implementation contract

**Status:** current host/protocol implementation + current-pin Servo worker source; exact build/deployment evidence remains gated  
**Module:** `browser.servo`  
**Current upstream pin:** `servo/servo@84bcc9ac701874fa9819e5cdee06356b961d736c`  
**Canonical pin source:** `third_party/servo-patches/MANIFEST.json`

This document promotes the still-valid isolation decisions from the historical WEB-C1 browser work into the current module documentation. Historical source/API assertions tied to older Servo commits are **not** carried forward as facts. Any Servo API, feature or source-topology statement must be revalidated against the current pin above before it becomes a build gate.

## 1. Trust boundary

The browser engine is not embedded into Agentd and is not exposed through a public WebDriver/CDP listener. One browser profile generation owns one isolated worker process. The parent owns process lifecycle, profile directory, authority checks, operation journal and the private control channel.

The worker receives no ambient authority from its existence. In particular:

- no TCP/UDP/HTTP/WebSocket automation listener is part of the Hepta control plane;
- no raw WebDriver or CDP command passthrough is a registered browser operation;
- arbitrary caller JavaScript, preference mutation, cookie/storage export and profile export are outside the public action vocabulary;
- raw credentials and host filesystem paths are not browser action payloads;
- a source pin or worker artifact digest is not runtime/effect authority.

## 2. Current implementation

| Surface | Current source | State |
| --- | --- | --- |
| typed browser actions | `src/action.js` | implemented |
| proposal -> effect bridge | `src/bridge.js` | implemented |
| serialized profile/effect state machine | `src/runtime-host.js` | implemented |
| stable owner-boundary facade | `src/runtime.js` | implemented |
| durable effect journal | `src/journal.js` | implemented |
| private worker frame codec | `src/worker-protocol.js` | implemented |
| artifact-bound subprocess driver | `src/worker-driver.js` | implemented |
| Linux Bubblewrap launcher | `src/worker-driver.js` | implemented; target-host execution evidence required |
| current-pin Hepta-owned Servo worker source | `servo-worker/` | implemented against the exact current pin; exact build receipt still required |
| real worker compile/repro/SBOM gate | `.github/workflows/hepta-browser-servo-worker-dev.yml` | implemented gate; only a terminal-success exact-SHA run is evidence |
| macOS / Windows equivalent isolation | none | not implemented |
| credential-reference broker into the worker | none | not implemented; raw credential action remains fail-closed |

The repository therefore contains both sides of the local process boundary, but source presence is not an artifact qualification claim. The selected binary must still be produced reproducibly and bound to an exact receipt before composition.

## 3. Private protocol

The worker channel uses a four-byte big-endian frame length followed by canonical JSON. The encoded body is at most 1 MiB. Every frame binds protocol version, session/profile identity, profile generation, monotonic sequence, message kind, request identity and canonical payload digest.

Missing/unknown fields, non-canonical JSON, invalid lengths, payload-digest drift, response sequence drift, cross-session/generation responses and unexpected frame kinds fail closed. The command vocabulary is `start`, `observe`, `dispatch`, `reconcile` and `stop`.

A protocol acknowledgement proves only a local worker observation. It is not proof that a remote navigation, form submission, download or business transaction completed. Such operations remain `indeterminate` until trusted terminal evidence is reconciled.

## 4. Effect linearization

For a new effect, the host:

1. validates page/document generation, typed action, destination, final payload digest, effect grant, epoch and deadline;
2. rejects an operation ID whose immutable request digest differs from a prior durable identity;
3. enters `authority.withVerifiedUse(request, callback)`;
4. inside that final-use fence, binds the VerifiedUse witness, fsyncs durable dispatch identity and sends one local worker command;
5. releases the authority fence after the local dispatch boundary, not after the remote business outcome;
6. persists terminal or indeterminate observation.

This prevents a successful revocation update from racing between final validation and local dispatch, and prevents a crash/driver exception after dispatch from becoming permission for a second dispatch. Reconciliation is observational: expired or revoked authority blocks a **new** effect but cannot erase or block reconciliation of an already-dispatched identity.

## 5. Typed action boundary

The closed action set is:

- `navigate { url, policyDigest, expectedRevision }`;
- `click { selector }`;
- `type { selector, text }`;
- `credential { selector, credentialRef }`;
- `upload { selector, fileRef, fileDigest, maxBytes }`;
- `focus { selector }`;
- `scroll { deltaX, deltaY }`;
- `wait { condition, timeoutMs }`;
- `download { url, maxBytes }`.

All fields are bounded and unknown fields reject. Credential and upload actions carry references rather than host paths or raw secret bytes. The current Servo worker deliberately returns `capability_not_connected` for credential/upload/download until their dedicated final-use brokers and terminal observers exist.

## 6. Linux isolation path

`LinuxBubblewrapLauncher` now starts from an empty tmpfs root rather than read-only binding the entire host filesystem. It admits only the immutable runtime paths required to execute the worker (`/usr`, optional `/bin`, `/lib`, `/lib64`, font/TLS configuration), private `/proc` and `/dev`, an empty/private home/tmp/runtime view, the one writable profile root and the exact verified worker artifact. `/var`, service roots, arbitrary host mounts and ambient user homes are not admitted.

The launcher also uses `--unshare-all`, no `--share-net`, `--clearenv`, a new session and parent-death cleanup. `scripts/linux-sandbox-probe.js` is an executable target-host probe: it checks an external host-only secret is invisible, a private profile is writable and direct external IPv4 connect fails. This is stronger than argv inspection, but a pass is still bound to the exact host/kernel/Bubblewrap identity that executed it.

## 7. Current-pin Servo worker

`servo-worker/` is an out-of-tree Hepta-owned executable using the exact current Servo Git pin with `default-features = false` and the selected `background_hang_monitor` + `bundled` feature set. It creates one software rendering context and one `WebView`, denies Servo permission requests, denies navigation outside the admitted HTTP(S) origin set, and speaks only the Hepta private framed protocol over inherited stdin/stdout.

Caller-provided JavaScript is not a registered action. Click/type/focus/scroll use worker-owned fixed templates parameterized by bounded typed fields. Navigation uses `WebView::load`. Credential/upload/download remain fail-closed rather than silently widening capabilities.

## 8. Exact build and reproducibility gate

`.github/workflows/hepta-browser-servo-worker-dev.yml` is the source-level artifact gate. For an exact candidate SHA it:

- installs the pinned Rust 1.88.0 toolchain and explicit Servo prerequisites;
- verifies or creates a candidate `Cargo.lock` and binds the exact Servo pin;
- captures full Cargo feature metadata and rejects `webdriver_server` in the worker dependency graph;
- runs `cargo check --locked` and the Browser JavaScript tests;
- executes the real Bubblewrap isolation/egress probe;
- performs two independent `cargo build --release --locked` builds using the same source date and remapped source path, and requires byte-for-byte equality;
- boots/stops the real produced worker through `SubprocessBrowserDriver` and Bubblewrap;
- emits worker SHA-256, deterministic SPDX-2.3 dependency SBOM and a checksum-bound build receipt.

If any step fails, the correct state is **artifact not qualified**. A generated lock is only a candidate until its exact bytes are reviewed and committed; subsequent selected builds must use that committed lock with `--locked`.

## 9. Remaining credential boundary

Linux ambient credential-store visibility is now denied by the filesystem allowlist, but functional credential use is intentionally not connected. The eventual credential broker must resolve `credentialRef` only at a separately authorized final-use seam, transfer the minimum bytes over an inherited private channel, never serialize raw secrets into the Browser journal/control protocol/logs, and make revocation-to-use ordering equivalent to the kernel final-use contract. A JSON witness returned before a later asynchronous dispatch is insufficient because it would reopen a revocation race.

## 10. Worker acceptance gates

Selection for composition requires exact evidence for:

- current source commit/tree, patch manifest and committed dependency lock;
- reproducible worker artifact and SPDX SBOM;
- private protocol conformance against the real binary;
- no WebDriver/CDP/network control listener;
- OS-enforced external egress denial;
- cross-profile cookie/cache/storage isolation;
- credential non-export and functional broker isolation where credential use is enabled;
- parent death, timeout and worker crash cleanup without redispatch;
- stale page/element rejection;
- trusted terminal/indeterminate reconciliation for real effects;
- measured memory, descriptors, observation cost and other selected-host budgets.

## 11. Cross-platform requirement

Linux is one concrete host path. Production portability still requires separately reviewed macOS and Windows launchers with equivalent private control, executable binding, profile isolation, credential/environment isolation, process-tree cleanup, resource limits and egress policy. A Linux pass cannot certify either platform.

## 12. Production composition boundary

The current kernel `VerifiedUseToken` is deliberately non-serializable and final use occurs synchronously under the live revocation fence. Therefore production Agentd -> Browser composition must not replace it with a pre-issued JSON "verified" receipt. A cross-process authority handoff must hold or otherwise preserve the same final-use linearization until the Browser durable-dispatch + local-worker-dispatch boundary is crossed. This is a cross-owner integration gate, not something the Browser adapter may self-issue.

## 13. Completion boundary

The repository can now claim source implementation of the hardened durable Browser owner boundary, private worker protocol, exact-pin Servo worker source, restricted Linux launcher, reproducible-build/SBOM gate and executable Linux isolation probes. It cannot claim an exact Servo artifact until that exact-SHA workflow succeeds and the lock/artifact receipt is retained. It also cannot yet claim functional credential-store integration, production Agentd caller composition, macOS/Windows equivalence, target deployment qualification, operator acceptance, promotion or release.
