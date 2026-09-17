# browser.servo isolated worker implementation contract

**Status:** current host/protocol implementation + remaining Servo artifact work  
**Module:** `browser.servo`  
**Current upstream pin:** `servo/servo@84bcc9ac701874fa9819e5cdee06356b961d736c`  
**Canonical pin source:** `third_party/servo-patches/MANIFEST.json`

This document promotes the still-valid isolation decisions from the historical WEB-C1 browser work into the current module documentation. Historical source/API assertions tied to older Servo commits are **not** carried forward as facts. Any Servo API, feature or source-topology statement must be revalidated against the current pin above before it becomes a build gate.

## 1. Trust boundary

The browser engine is not embedded into Agentd and is not exposed through a public WebDriver/CDP listener. One browser profile generation owns one isolated worker process. The parent owns process lifecycle, profile directory, authority checks, operation journal and the private control channel.

The worker receives no ambient authority from its existence. In particular:

- no TCP/UDP/HTTP/WebSocket automation listener is part of the Hepta control plane;
- no raw WebDriver or CDP command passthrough is a registered browser operation;
- arbitrary JavaScript evaluation, preference mutation, cookie/storage export and profile export are outside the current public action vocabulary;
- raw credentials and host filesystem paths are not browser action payloads;
- a source pin or worker artifact digest is not runtime/effect authority.

## 2. Current host implementation

The repository currently implements the following host-side pieces in `apps/hepta-browser`:

| Surface | Current source | State |
| --- | --- | --- |
| typed browser actions | `src/action.js` | implemented |
| proposal -> effect bridge | `src/bridge.js` | implemented |
| serialized profile/effect state machine | `src/runtime-host.js` | implemented |
| stable owner-boundary facade | `src/runtime.js` | implemented |
| durable effect journal | `src/journal.js` | implemented |
| private worker frame codec | `src/worker-protocol.js` | implemented |
| artifact-bound subprocess driver | `src/worker-driver.js` | implemented |
| Linux Bubblewrap launcher | `src/worker-driver.js` | implemented host path; target execution evidence still required |
| current-pin Servo worker executable | none | not implemented |
| macOS / Windows equivalent isolation | none | not implemented |
| credential broker into a qualified worker | none | not implemented |

The host code can therefore enforce the boundary around an exact worker artifact, but the repository does not yet contain or certify the actual Servo worker binary.

## 3. Private protocol

The worker channel uses a four-byte big-endian frame length followed by canonical JSON. The encoded body is at most 1 MiB. Every frame binds:

- protocol version;
- session/profile identity;
- profile generation;
- monotonic channel sequence;
- message kind;
- request identity;
- canonical payload digest.

Missing/unknown fields, non-canonical JSON, invalid lengths, payload-digest drift, response sequence drift, cross-session/generation responses and unexpected frame kinds fail closed. The current command vocabulary is limited to `start`, `observe`, `dispatch`, `reconcile` and `stop`; `response` / `event` are worker-to-host categories.

A protocol acknowledgement means only that the isolated worker received the local command. It is not proof that a remote navigation, form submission, download or business transaction completed. Such operations remain `indeterminate` until a trusted terminal observation is reconciled.

## 4. Effect linearization

For a new effect, the host performs these steps in one profile-serialized path:

1. validate page/document generation, typed action, destination, final payload digest, effect grant, epoch and deadline;
2. reject an operation ID whose immutable request digest differs from a prior durable identity;
3. enter `authority.withVerifiedUse(request, callback)`;
4. inside that final-use fence, bind the VerifiedUse witness, fsync the durable dispatch identity and send the command across the private local worker channel;
5. release the authority fence after local dispatch, not after the remote browser/business outcome;
6. persist any observed terminal/indeterminate result.

This ordering prevents a successful revocation update from racing between the final authority check and the local effect dispatch. It also ensures a crash or driver exception after the dispatch boundary cannot turn into permission for a second dispatch.

Reconciliation is observational. Expired/revoked authority blocks new effects but does not erase or block reconciliation of an already-dispatched identity.

## 5. Typed action boundary

The current closed action set is:

- `navigate { url, policyDigest, expectedRevision }`;
- `click { selector }`;
- `type { selector, text }`;
- `credential { selector, credentialRef }`;
- `upload { selector, fileRef, fileDigest, maxBytes }`;
- `focus { selector }`;
- `scroll { deltaX, deltaY }`;
- `wait { condition, timeoutMs }`;
- `download { url, maxBytes }`.

All fields are bounded and unknown fields reject. Navigation binds the normalized URL, policy digest and expected revision into the final payload digest. Credential and upload actions contain only references; raw secret bytes, profile paths and arbitrary host paths are not legal action fields.

The actual credential broker remains a missing integration: a qualified implementation must resolve `credentialRef` only at the isolated final-use boundary, avoid logs/journals/page observations, and zero/retire transient buffers according to the selected platform runtime.

## 6. Linux isolation path

`LinuxBubblewrapLauncher` provides the current concrete launcher contract. It constructs a process with:

- `--unshare-all` and no `--share-net`;
- a new session and parent-death cleanup;
- cleared environment;
- ambient `/home`, `/root`, `/run` and `/tmp` replaced;
- a private writable profile mounted at `/hepta-profile`;
- the exact verified worker artifact mounted read-only as `/hepta-worker`;
- inherited stdin/stdout pipes as the control channel.

The root filesystem is currently read-only bound to satisfy dynamic runtime/library dependencies. Sensitive user homes and runtime directories are hidden, but this is not the final minimal filesystem allowlist. Qualification must inventory remaining readable paths and narrow them where the selected Servo toolchain allows.

Linux code presence is not Linux deployment evidence. A target-host test must prove that the selected Bubblewrap binary and kernel configuration actually establish the namespaces, that the worker has no reachable external egress/control listener, and that descendants die on parent/session termination.

## 7. Servo worker target

The next implementation artifact is a Hepta-owned out-of-tree worker built against the exact current Servo source pin. It must use Servo's supported embedding API rather than expose the upstream WebDriver server as the Hepta API.

Before source is admitted, revalidate against `84bcc9ac701874fa9819e5cdee06356b961d736c`:

1. exact public embedding types/methods needed for one WebView;
2. exact Cargo feature closure and forbidden feature set;
3. whether any source patch is required;
4. absence of `webdriver_server` from the worker dependency graph;
5. one-process / one-WebView state topology;
6. platform event-loop/rendering integration for each supported OS.

Do not copy the older `0a48e298...` topology receipt forward without this revalidation; it described a different upstream tree.

## 8. Worker acceptance gates

A Servo worker may be selected for composition only when exact evidence establishes all of the following:

- source commit/tree matches the canonical pin and patch manifest;
- reproducible build inputs and toolchain identities are sealed;
- worker binary SHA-256 and SBOM are produced and independently checked;
- private protocol conformance tests pass against the real binary;
- no WebDriver/CDP/network control listener is reachable;
- C1 external egress is denied by the OS boundary;
- one profile/session cannot read another profile's cookie/cache/storage state;
- credential references cannot be exported or observed as raw page/evidence payloads;
- parent death, timeout and worker crash clean descendants/profile state without redispatch;
- stale page/element generations cannot cause an effect in a successor document;
- real navigation/download effects have trusted terminal or indeterminate reconciliation evidence;
- target memory, descriptor, tab and observation budgets are measured, not inferred from design ceilings.

## 9. Cross-platform requirement

Linux is only one host path. Production portability still requires separately reviewed macOS and Windows launchers with equivalent properties: private inherited control channel, no ambient automation listener, exact executable binding, private profile root, environment/credential isolation, process-tree cleanup, resource limits and egress policy. A Linux pass cannot certify either platform.

## 10. Completion boundary

The current repository can truthfully claim a hardened, durable JavaScript owner boundary plus an artifact-bound private subprocess/sandbox host path. It **cannot** yet claim a built Servo worker, real Servo WebView execution, cross-platform sandbox qualification, credential-store integration, production caller composition or deployed external-effect qualification.

Those missing artifacts remain implementation work; they are not converted into documentation closure by this specification.
