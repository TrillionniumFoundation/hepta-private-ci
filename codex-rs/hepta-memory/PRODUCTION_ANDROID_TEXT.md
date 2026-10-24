# Original Android text target: development and technical contract

## Scope and current qualification

`ProductionAndroidTextTarget` adapts one explicitly qualified original Android
editor to the existing `ProductionFinalUseOutboxDispatcher`. It neither opens a
writer nor issues authority. It is not registered by default Agentd startup.
The original host must supply its existing production lease/verifier, FinalUse
authority and grant provider, and the already retained device capability.

The matching Desktop receiver lives in `support/android/receiver/`: it patches
the same original Pocket4 fixed helper and the same original ActionRunner APK.
There is no new runtime, device discovery service, ADB route or operation DB.

Current source qualification consists of a synthetic cross-language wire
fixture and focused owner-adapter cases. Compilation, original FinalUse/owner
runtime composition and real device effects must be recorded separately. A
trait implementation or synthetic reply does not establish a trusted host,
original helper/source pin, package signature, peer identity or live grant.

## Development map

| File | Responsibility |
| --- | --- |
| `src/production_android_wire.rs` | Bounded canonical native observation and exact text payload |
| `src/production_android.rs` | Original intent, typed device seam, synchronous FinalUse destination |
| `src/production_android_response.rs` | Actual apply acknowledgement and independent native readback validation |
| `src/production_android_tests.rs` | Exact bytes, no deferred entry, lost ack, stale/changed identity regressions |
| `tests/fixtures/android-bound-text-v1.json` | Python-generated UTF-8/hash fixture, explicitly synthetic |

Run from `codex-rs` with the repository toolchain:

```sh
just fmt
just test -p codex-hepta-memory production_android
just fix -p codex-hepta-memory
```

The focused cases do not launch Android. Original device acceptance must use
the separately recorded native runner/helper sources and the actual original
host capability. No Rust dependency or lockfile change is needed.

## Payload and recipient identity

`AndroidSetTextV1::from_json` accepts at most 16 KiB of exact canonical UTF-8.
Unknown/duplicate fields, noncanonical JSON, malformed native identities,
inconsistent node hashes, text over 4,096 UTF-8 bytes, and invalid original
StableId characters reject. Every serialized struct is ordered lexicographically
to match the Python and Java receiver. Chinese text and emoji retain exact
UTF-8 bytes.

The observation binds the actual host boot/init/namespace generation, target
application PID/start time, focused WindowManager token/activity/bounds, exact
resource/class/bounds/prior-text node hash, native pixel-scope hash and monotonic
time. `atomic_snapshot=false` is required. Numeric PIDs alone are insufficient.

The canonical scope object has exactly `application`, `generation`, `package`
and `resource_id`. Its SHA256 is both the operation scope digest and the suffix
of `pocket4.android:<scope-sha256>`. That 79-byte destination fits the original
128-byte StableId bound. Different incarnations or different editors cannot
collide by merely reusing an application name. The complete immutable native
observation, replacement text and original expiry are included in the payload
digest and original semantic operation digest.

The original `OperationIntentV1` contains no destination-transaction predecessor
capability. Android accessibility can re-read preconditions immediately before
performing the action, but it does not expose an atomic compare-and-set with
application state. Claiming the Notes CAS contract here would be inaccurate.
Any supplied `expected_predecessor_sha256` is therefore rejected by this target.

## Original owner composition

The existing trusted host obtains a native `organ-observe` response through
the original qualified helper capability. It validates that reply's actual
host/source/package identity and creates the target with the native observation
and an `Arc<dyn OriginalAndroidTextDevice>` supplied by that same host. It can
attach the target using the existing
`AgentdProductionOperationRuntimeConfig::with_additional_target`, together with
the original corresponding FinalUse authority. No second writer is opened.

For a proposed text change, construct the canonical payload, call
`android_text_operation_intent` with the original subject and policy generation,
and persist that intent plus the same payload using the original writer's
`prepare_operation` path and topic `hepta.android.set-text.v1`. Dispatch remains
through the original queued receipt and FinalUse dispatcher. Do not call this
target directly as a replacement for original authorization.

`OriginalAndroidTextDevice` is an explicit bootstrap boundary, not an ambient
shell or a discovery mechanism. Its implementation must use the already
authorized original Runtime/host connector, preserve its peer/host and fixed
tool/source pins, send only the provided fixed-helper operation, and perform
bounded synchronous calls without reconnect/replay. `apply` accepts only
`organ-set-text`; `readback` accepts only `organ-readback` and must start a
separate read-only invocation. The adapter passes the exact original payload
base64 and SHA256 in both calls. Changing operation identity, rebinding a
deadline or routing to a fresh cell is forbidden.

This source increment does not invent an implementation of that capability
from a hostname, user request, JSON boolean or a synthetic grant. The actual
original connector implementation and its measured deployment remain required
composition evidence. The default read-only Desktop profile stays unchanged.

### Concrete original bootstrap locations and missing connector

A full local source search on 2026-10-24 found no Runtime Full Operator server,
client bootstrap or concrete production `OriginalAndroidTextDevice` in either
Desktop or Hepta. The only implementation in these trees is the deliberately
synthetic test device. The installed ChatGPT Runtime connector's availability
does not by itself install its authenticated client into an Agentd process.

The existing integration points are:

- `hepta-agentd/src/production_composition.rs`: constructs the existing
  `AgentdProductionOperationRuntimeConfig` using the original recovered owner.
- `hepta-agentd/src/production_writer_host.rs`: `with_additional_target` accepts
  the original destination-specific FinalUse authority and target; `attach`
  verifies that it is the same recovered writer/lease before registration.
- `hepta-agentd/src/notes_bootstrap.rs`: existing channel-factory → target →
  additional-target wiring is a useful model. Its inherited Notes descriptors
  are not Android capabilities and cannot be repurposed as such.

When the original host supplies its real retained Runtime connector, the
concrete connector implementation must satisfy this fixed one-shot contract:

| Boundary | Exact input / required behavior |
| --- | --- |
| Original Runtime target | Existing configured host alias `pocket4`, retained authenticated client/peer; no raw SSH address or new login |
| Fixed process entry | `/usr/bin/sudo`, argv `-n`, `/usr/local/libexec/android-digitalis-observe-helper`; no shell command fragments |
| `apply` stdin | The exact JSON bytes supplied by this target: `op=organ-set-text`, original `payload_base64`, original `payload_sha256`; write once and close stdin |
| `readback` stdin | Same original payload and hash, `op=organ-readback`; a new read-only invocation, never a cached earlier observation |
| Native observation input | `{"op":"organ-observe","package":"<verified exact package>","resource_id":"<observed exact full ID>"}` through the same fixed helper |
| Input bound | At most 24 KiB for the outer helper request; the decoded original payload remains at most 16 KiB |
| Result | Only complete UTF-8 stdout from the same original job after confirmed exit; at most 8 KiB for the receiver reply; nonzero exit/late/incomplete/oversized output is unresolved |
| Runtime job identity | Retain the returned original Runtime job ID with the same operation. A successful `process_start` acknowledgement is not a native effect receipt |
| Deadline and cancellation | Bound the synchronous host call and every poll; never reset native payload expiry. Cancellation invalidates the effect lane; stopping a process does not prove that Android did not act |
| Source gates | Exact deployed root-owned helper hash, original Droidloom file/owner, installed APK hash and original signer, original host/peer and same cell generation before use |

If the original Runtime method accepts an idempotency key, bind the first effect
attempt to a deterministic digest of the original operation ID and payload hash.
Do not invent another operation ID on reconnect. An unknown start result without
a retained original job/receipt stays unknown; this adapter must not start an
effect again merely to rediscover its result. A new read-only recovery query can
observe state, but cannot upgrade that unknown result to Committed.

Desktop's `support/android/receiver/qualify_receiver.py` provides local `java`,
`apk` and `installed` gates for the source/signature part of this contract.
Installed inspection requires the existing original root inspection capability;
the tool does not self-elevate or create a new helper lane. These gates produce
reviewable source evidence while the original authenticated connector bootstrap
and live grant remain explicit composition blockers.

## Completion, loss and recovery

The actual device `apply` call and independent `readback` call execute during
the existing synchronous FinalUse consumer-entry closure, before a future is
returned. Polling or dropping that future cannot schedule a new effect. The
receiver checks the immutable at-most-30-second action expiry; it is never
refreshed by this adapter.

Immediate `Committed` requires all of the following evidence together:

1. An actual original receiver success response for the same operation/payload
   and original cell, confirming exact preconditions, action submission,
   non-password UTF-8 readback and restoration of accessibility mode.
2. A separate original readback for the same cell, application incarnation,
   WindowManager token and exact node, containing the requested text hash.
3. A native readback timestamp no earlier than the native action-observation
   timestamp. The adapter recomputes matching text instead of trusting only
   `state_matches_requested_value`.

The resulting receipt retains both exact receiver JSON replies. The existing
original writer owns durable publication of that receipt and terminal status.
This proves an acknowledged text-field effect and its observed postcondition;
it does not assert arbitrary app business success or persistence of the field
after application termination.

Any lost/malformed apply acknowledgement, failed later readback, changed
incarnation, stale timestamp or contradictory operation stays Indeterminate.
The effect lane is invalidated and never re-entered automatically. The retained
read-only lane can inspect the same original operation.

`observe_terminal` always treats matching current text as **Indeterminate**.
Readback alone cannot prove that the original operation caused the state. A new
application/cell with identical text is unavailable to the old operation, not
an alternative destination and not proof of NotApplied. A source crash after
the effect but before durable receipt publication therefore stays unresolved
unless the original source already has a terminal receipt. There is no new
receipt ledger or state-based replay heuristic to conceal this limitation.

## Runtime acceptance that remains required

Record one source pair, native package signer equality and the deployed helper
hash. Select an actual harmless Settings search editor or an owned test
application and discover its exact resource ID. Use the original lease,
authorization entry, FinalUse grant and retained operation to perform one
Chinese-text effect and independent readback, then read the durable original
writer status.

Exercise lost reply, cancellation, revocation, owner restart, application
restart and cell generation change. A surviving terminal source receipt should
remain terminal; absent causal evidence must remain unresolved with zero new
effect attempts. This contract intentionally does not claim that a generic
Android editor can recover an unacknowledged effect causally across process
death. Closing that stronger property requires an application-owned causal
receipt contract on the selected real application, not another device ledger.
