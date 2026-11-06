# Ordinary PQ PoN effect packet transport v1

## Purpose and compatibility

The original ordinary effect API carries a hexadecimal payload in one newline-delimited JSON frame. Its 24 KiB decoded-payload limit and 64 KiB JSON-frame limit cannot carry the fixed Chain qualification packet, which is 49,508 bytes before hexadecimal expansion. An empty transaction list does not remove the packet's proof bytes.

The new `AutomationExecuteEffectPacketV1` request is a separately advertised transport. It carries the existing authorized intent, signed FinalUse grant, command ID and `wire_len` in the bounded JSON header, followed by the complete raw packet and a write-side EOF. It preserves the ordinary AutomationStore, FinalUse nonce owner, taskflow fence, operation identity, provider outbox and receipt readback. It does not split a packet, strip proof bytes, substitute a synthetic provider, retry a failed transport or fall back to the old API.

The old `AutomationExecuteEffect` request and all of its size limits remain unchanged. Historical failure evidence for that API remains valid. Qualification of v1 must not be recorded as success of the old inline protocol.

## Admission contract

| Input or resource | Rule |
| --- | --- |
| Capability | `automation.external_effect_packet`, major version 1; advertised only for an ordinary PoN adapter backed by ML-DSA-65 FinalUse authority |
| Header | One complete newline-delimited JSON request within the existing 65,536-byte control-frame bound |
| Body | Nonempty, at most 65,536 bytes; this matches the existing durable effect ledger ceiling |
| Framing | Exactly `wire_len` bytes, followed by EOF; truncation and any trailing byte are rejected |
| Integrity | SHA-256 of all raw packet bytes must equal the authorized intent's payload digest |
| Authorization | Existing subject, destination, scope, taskflow fence, PQ issuer/revocation/frontier and FinalUse checks remain authoritative |
| Bulk retention | Two per-server permits; a permit follows a packet into a blocking provider worker and is released only after the last owner drops it |
| Time | Existing control request deadline is carried through packet reception, effect dispatch and native provider admission; the provider uses the earlier of that deadline and its own configured timeout |
| Unknown outcome | A transport error does not authorize replay; reconcile the original effect identity |

The 64 KiB body limit is checked before allocating the body or claiming the FinalUse nonce. The initial qualification candidate used a 1 MiB transport bound; independent review found that the existing ledger rejects bodies above 64 KiB after the FinalUse claim. The final transport is narrowed to the ledger's existing ceiling. The ledger limit itself is not increased.

## Cancellation and native entry

The execution token is checked before admission and again after body verification, before and after blocking queue handoff, after preparation of the pinned provider binary, and immediately before native process creation. The subprocess runner observes cancellation after entry and performs bounded direct-child cleanup. Any cancellation, timeout or incomplete output after process entry remains an unknown dispatch outcome; it is never reclassified as a proof of non-dispatch.

These checks do not make cancellation atomic with OS process creation. The cleanup grace is not an extension of the success deadline. The transport's two permits bound this new packet path, not all daemon memory, all provider children, existing inline requests or historical reconciliation work.

## Required qualification

Qualification must bind the tested Hepta commit and tree, unchanged Cargo lockfile and nextest configuration, native toolchain, test executable hashes, and the exact Chain source/build/binary identity. Retain every failed and successful attempt separately.

The required checks are:

1. Protocol serialization and client behavior, including capability refusal, bounded headers, full raw bytes, identity-checked responses, timeout and no fallback.
2. Server framing under coalesced and fragmented input; zero, oversized, truncated and trailing bodies; digest mismatch; permit exhaustion and lifetime; cancellation and deadline handling.
3. Ordinary PQ host rejection before authority consumption for invalid bindings, a classical or non-PoN owner, cancellation, and a 65,537-byte body. Nonce and durable-attempt state must remain unchanged on pre-admission refusal.
4. Native direct-child tests for pre-entry refusal, exact 49,508-byte stdin/stdout, and post-entry cancellation yielding an unknown result with cleanup.
5. The fixed full Chain packet on the original `legacy-v2` and `authenticated-v1` state backends, through both the ordinary PQ host and the real control socket/public client.
6. Exact historical receipt readback after closing and reopening the real stores and owner, with trust services and the provider namespace subsequently unavailable, without another nonce claim or provider-store recreation.
7. Cold rollback of the complete local Automation/FinalUse directory and Chain namespace after nonce consumption and after signed revocation, on both backends. Close the SQLx pool and every authority owner before copying or restoring files; retain the external frontier's future history; replay the original signed bytes. The ordinary loader must reject twice with `AntiRollbackViolation`, and the retained frontier and restored authority/provider files must remain unchanged. Record the original Chain pair and the final integrated Chain pair separately.

The socket qualification fixture explicitly establishes daemon readiness for this component test. It does not start the production AppServer or execute the daemon's Evidence startup gate. Its result is not a full production startup, deployment, or end-to-end PQ task/evaluator qualification.

The cold rollback test restores local owner state while its fixture clock and CAS frontier remain outside the restored directories. This is a component test of the external-frontier contract. It does not establish independently deployed custody or resistance to simultaneously rolling back every holder of the future history.

## Claims retained outside this transport

Passing these checks establishes bounded transport of a full packet through the ordinary PQ FinalUse owner. It does not independently establish production trust custody, complete software/configuration release roots, PQ requester/source/evaluator authority, persistent cross-owner rollback resistance, confidentiality of every listener, arbitrary-fork continuous recovery, or quantum PoN work-cost and fork-choice security. Those gates need their own fixed-source evidence and owners.
