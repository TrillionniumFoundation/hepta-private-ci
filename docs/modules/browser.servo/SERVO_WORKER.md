# browser.servo current Servo worker contract

**Status:** current implementation contract; host-side boundary implemented;
actual Servo worker artifact and independent OS qualification remain open.

**Current Servo pin:** `84bcc9ac701874fa9819e5cdee06356b961d736c` from
`third_party/servo-patches/MANIFEST.json`.

This document replaces reliance on the historical `docs/hepta-vnext/browser/*`
worktree for current development. Those ADRs remain useful provenance, but they
were authored against a different Servo source pin and are not normative for the
current checkout unless revalidated here.

## 1. Process and transport model

One admitted browser profile generation owns one browser worker process. The
control plane is not TCP, HTTP, WebSocket, WebDriver, or a discoverable Unix
socket. The host creates one inherited private duplex channel at file descriptor
3 and speaks `hepta.browser.worker.v1` over four-byte big-endian length-prefixed
JSON frames, with a 1 MiB frame ceiling and monotonically increasing host
sequence.

The host-side implementation is `apps/hepta-browser/src/servo-process-driver.js`.
It verifies the exact worker and sandbox-launcher SHA-256 digests before spawn.
The child environment is empty except for values explicitly installed by the
sandbox recipe. Raw credentials are never placed in argv, environment variables,
receipts, or the browser action payload; browser actions carry only bounded
credential references.

## 2. Linux C1 sandbox

`LinuxBubblewrapSandbox` is the current Linux launch contract. It uses:

- `--die-with-parent` and a new session;
- private PID, network, IPC and UTS namespaces;
- `--clearenv`;
- a private read/write profile bind;
- read-only worker and system-library bindings;
- private `/tmp`;
- inherited control fd 3;
- `--unshare-net`, so C1/local-fixture execution has no external egress.

The host rejects a start observation that does not bind process, profile,
credential and network-policy enforcement plus non-zero sandbox and network
policy digests. This is a fail-closed host contract; independent target-host
observation is still required before activation.

macOS and Windows equivalents are not implemented in the current source. They
must preserve the same no-listener, one-process/one-profile-generation,
credential-reference-only and external-egress policy semantics rather than
silently falling back to an unsandboxed worker.

## 3. Typed browser effects

`apps/hepta-browser/src/actions.js` defines the closed v1 action vocabulary:

- `navigate { url }`
- `click { selector }`
- `type { selector, text }`
- `scroll { deltaX, deltaY }`
- `focus { selector }`
- `wait { milliseconds }`
- `download { url, downloadRef, maxBytes }`
- `upload { selector, fileRef, maxBytes }`
- `credential_fill { selector, credentialRef }`

Every action is normalized and size bounded. The canonical typed-action digest
must equal the effect grant's `finalPayloadDigest`, the supplied
`finalPayloadDigest`, and the VerifiedUse witness binding. URL-bearing actions
also bind the exact destination origin; page-local actions bind the current page
origin.

No arbitrary JavaScript evaluation, raw cookie/storage export, profile-path
export, preference mutation, unrestricted WebDriver command, or raw credential
value is part of v1.

## 4. Final-use authority linearization

A new effect is admitted only after all of the following agree:

1. profile/principal/generation and current page/document generation;
2. typed action kind and canonical payload digest;
3. allowed origin and destination origin;
4. registered effect grant, authority epoch and expiry;
5. VerifiedUse witness digest/payload/epoch binding and expiry;
6. the injected `authority.verifyFinalUse` port's current authorization result,
   revocation revision and authority receipt digest;
7. the operation deadline after the final authority check.

The authority observation is bound into the operation semantics before the
pre-dispatch journal intent is fsynced. No effect is dispatched if final-use
verification or the durable intent fails.

## 5. Exactly-once safety and recovery

`navigateOrAct` serializes profile mutations. Before `driver.act` it writes a
mode-0600 atomic durable intent with an `indeterminate` receipt and reserves the
operation in memory. Therefore:

- concurrent calls with one operation ID cannot both dispatch;
- a driver throw/timeout after a possible remote effect cannot make the ID fresh;
- process restart reloads outstanding operation identities;
- replay never reruns final authority verification or redispatches an existing
  operation;
- changed immutable semantics are rejected;
- terminal receipts are retained durably while the in-memory terminal cache is
  bounded independently from the 1024 outstanding-effect ceiling.

Reconciliation uses the stored semantics and typed payload. It intentionally
allows an expired old profile lease, grant, witness, and action deadline because
it observes an existing effect instead of authorizing a new one. Reconciliation
has its own bounded deadline.

## 6. Redirect/origin containment

A page observation outside the admitted origin set immediately quarantines the
profile and invokes driver containment (or stop when no separate containment
method exists). New effects from a quarantined profile are denied.

This post-observation quarantine is not a substitute for preventive network
policy. In C1 the Linux sandbox denies all external egress. A later networked
profile must implement destination/origin enforcement below the page content
layer and independently prove redirect, DNS, proxy, localhost/link-local and
credential isolation behavior before `networkPolicyEnforced=true` can be
accepted.

## 7. Current test requirements

The package test suite must include, at minimum:

- concurrent duplicate operation -> exactly one `driver.act`;
- throw after possible effect -> durable indeterminate, no redispatch;
- expired grant/profile/deadline -> reconciliation and cleanup still work;
- restart -> outstanding durable operation reload and reconciliation without
  dispatch;
- typed payload/destination/grant/VerifiedUse drift -> reject;
- final authority denial -> zero effect dispatch;
- timeout -> AbortSignal and indeterminate receipt;
- out-of-scope observed origin -> quarantine and new-effect denial;
- journal semantic reuse -> reject;
- Linux launch recipe -> network namespace, parent-death, clear environment,
  private profile and inherited fd 3.

These tests prove repository behavior only. They are not a Servo build receipt,
an OS isolation observation, a remote business terminal observation, independent
acceptance, activation, promotion or release evidence.

## 8. Remaining external/product gates

The following remain open and must not be collapsed into source-complete claims:

1. produce the reproducible `hepta-servo-worker` binary from the current Servo
   pin and bind exact source/tree/toolchain/features/artifact/SBOM digests;
2. implement the child-side `hepta.browser.worker.v1` adapter against the pinned
   Servo public embedding API;
3. run real local-fixture navigation, semantic observation, click/type/scroll,
   upload/download and credential-reference tests through the actual worker;
4. prove no WebDriver/TCP listener and no external egress under the selected C1
   Linux host;
5. add and independently qualify macOS and Windows isolation equivalents before
   claiming those hosts;
6. add a named non-test product caller through `runtime.agentd`/the registered
   module port;
7. collect real redirect, crash, parent-death, timeout, descendant-cleanup,
   profile/cookie/cache isolation and remote terminal-effect evidence.
