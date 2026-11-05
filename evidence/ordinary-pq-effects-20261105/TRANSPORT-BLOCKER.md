# Ordinary PQ → real Chain: fixed-source budget boundary

## Scope and conclusion

This is a read-only source review of Hepta `ee57cd57c322a8fecdf674a662c741452baf6478` and Chain `04be5f02c84cf5cb626a53f34bc03a5bd6ff5137`. No runtime read, test rerun, source edit, limit change, workload change, or Git mutation was performed for this review.

**Under the original ordinary Agentd budgets, this exact real Chain packet path is structurally blocked.** Chain's original `Packet` grammar has a minimum encoded size of **49,508 bytes**, already exceeding the ordinary decoded effect limit of **24,576 bytes**. Its hex representation alone is **99,016 ASCII bytes**, exceeding the **65,536-byte** control frame before the JSON envelope, intent, and signed grant are added.

The conclusion applies to the checked `04be` original `Packet` codec and the test's original configuration: `legacy-v2` / `authenticated-v1` state backends, `legacy-first-two-v3` evaluation policy, `legacy-task-v1` task profile, and `linear-expert-dev-v1` model profile. Both iterations call the same sealed `status` / `make` helper and the same packet codec. It is not a statement about unreviewed Chain commits, Growth packet variants, PQ application codecs, compression transports, or a future alternate protocol. The authenticated-v1 runtime iteration must not be marked passed merely because the source-level size bound also applies to it.

## Exact packet lower bound

| Component | Exact bytes | Fixed source |
| --- | ---: | --- |
| Header | 318 | [trnm-protocol/src/pon_wire.rs:9](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-protocol/src/pon_wire.rs#L9) |
| Transaction count | 2 | [trnm-pon-node/src/lib.rs:180–200](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/lib.rs#L180-L200) |
| Fixed proof | 49,188 | [trnm-crypto-primitives/src/pon_work.rs:20–25](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-crypto-primitives/src/pon_work.rs#L20-L25) |
| Minimum packet, zero transactions | **49,508** | `318 + 2 + 49,188` |

The proof calculation is `N = 64`, `CELLS = N * N = 4096`, and `PROOF_BYTES = 4 + 3 * CELLS * 4 + 32 = 49,188`. `Packet::checked_wire_length` requires the exact fixed proof length, starts with `HEADER_BYTES + 2 + proof.len()`, and adds positive length-prefix/payload bytes for every transaction. `Packet::decode` independently requires at least `HEADER_BYTES + 2 + PROOF_BYTES`, then requires the remaining bytes after transactions to equal exactly `PROOF_BYTES`. These are codec requirements, not a measurement assumption. [Packet length and decoding rules](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/lib.rs#L170-L234)

The original CLI `make` uses an empty transaction list when no `--transactions` file is provided. Removing transactions cannot reduce a packet below the above lower bound. [main.rs:2008–2019](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/main.rs#L2008-L2019)

## Original ordinary budgets and enforcement

| Layer | Bound or behavior | Fixed source |
| --- | --- | --- |
| Shared protocol constants | Control frame 65,536 bytes; decoded effect wire 24,576 bytes | [hepta-agent-protocol/src/lib.rs:62–63](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agent-protocol/src/lib.rs#L62-L63) |
| Agentd public constants | Reexports those shared constants | [hepta-agentd/src/lib.rs:129–131](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/lib.rs#L129-L131) |
| Control frame reader | Rejects an empty, oversized, or non-newline-terminated frame before request deserialization | [control.rs:125–133](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/control.rs#L125-L133) |
| Effect hex parser | Rejects empty, odd-length, or more than `24,576 * 2 = 49,152` hex characters before decoding | [state_control.rs:1147–1166](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/state_control.rs#L1147-L1166) |
| Ordinary effect host | Rejects empty or more than 24,576 raw bytes, then checks SHA256 of the complete supplied payload | [automation_effect_host.rs:1386–1409](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host.rs#L1386-L1409) |
| Lower-level PoN adapter | Permits up to 1,048,576 bytes before its exact child handoff; this larger bound does not override earlier host/RPC checks | [automation_effect_host.rs:289–315](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host.rs#L289-L315) |

The shared 65,536/24,576 constants are also present at the original Hepta `1556a4df6e279055fd8196f81a4ca2fe0f19384a` candidate. Its ordinary host already enforced the same raw-payload size and complete-payload digest. [Original protocol constants](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1556a4df6e279055fd8196f81a4ca2fe0f19384a/codex-rs/hepta-agent-protocol/src/lib.rs#L62-L63) · [Original ordinary host guard](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1556a4df6e279055fd8196f81a4ca2fe0f19384a/codex-rs/hepta-agentd/src/automation_effect_host.rs#L1342-L1365)

Consequently, `49,508 > 24,576` blocks direct ordinary host execution. Passing the same bytes through the existing RPC also fails: `49,508 * 2 = 99,016 > 49,152` at the effect hex budget and `99,016 > 65,536` at the enclosing control-frame budget. This arithmetic excludes JSON/authorization overhead, so adding those fields cannot remove the mismatch.

## Complete-payload authorization and recovery binding

The signature covers the canonical grant, whose binding includes the SHA256 of the **complete original wire payload**. It does not require concatenating all 49,508 packet bytes directly into the grant's signing input. This distinction does not permit changing or truncating the payload after authorization:

1. `AuthorizedEffectIntent::final_use_binding` derives the expected request/intent digest, subject, destination, scope, and payload digest inside the automation owner. The caller does not supply an independently mutable second binding. [authorized_effect.rs:163–176](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-automation/src/authorized_effect.rs#L163-L176)
2. Schema-2 `FinalUseGrant::signing_bytes` serializes the grant, including `binding.payload_sha256`, under `hepta.kernel.authority.final-use.pq.v2`. Authority verification checks the expected binding, profile, issuer key epoch window, and signature. [final_use.rs:49–99](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-contracts/src/final_use.rs#L49-L99) · [final_use.rs:622–641](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-contracts/src/final_use.rs#L622-L641)
3. Execution recomputes SHA256 over the supplied wire and checks the durable claimed step's exact intent and payload digests, then the expected FinalUse binding. [authorized_effect.rs:768–799](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-automation/src/authorized_effect.rs#L768-L799)
4. The PoN adapter recomputes the full-wire digest immediately before dispatch and exact observation/lookup. It sends those same bytes to `submit --packet-stdin` or `packet-status --packet-stdin`; there is no decoding of a compressed/reference payload in this checked handoff. [automation_effect_host.rs:263–315](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host.rs#L263-L315) · [automation_effect_host.rs:339–399](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host.rs#L339-L399)
5. Node's submit path reads one exact packet and invokes `Packet::decode` before native admission. A cropped proof fails the exact codec length checks. A digest alone is not a valid packet. Native exact observation compares the complete expected re-encoding with the stored packet and the retained packet before reporting identity-bound state. [main.rs:47–68](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/main.rs#L47-L68) · [main.rs:2002–2006](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/main.rs#L2002-L2006) · [store.rs:6022–6064](https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/04be5f02c84cf5cb626a53f34bc03a5bd6ff5137/trillionnium/crates/trnm-pon-node/src/store.rs#L6022-L6064)

Cropping bytes while retaining the original digest fails Hepta binding checks. Replacing the digest changes the authorized intent/grant and durable recovery identity, and the cropped packet still fails Node's codec. Replacing the packet by a digest or a compressed representation is not the existing exact-wire protocol.

## Qualification boundary

The checked test first initializes the namespace and generates the real packet, then enforces the original ordinary limit at lines 55–62. Its first PQ host open is only at line 98. [Test ordering](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq_chain_tests.rs#L33-L98)

Root independently retrieved and verified the runtime failure: 49,508 bytes exceeded 24,576 on the first `legacy-v2` iteration, before PQ host construction. This source-only review does not replace that log evidence. It explains why the observed size is also the original codec's structural minimum. There is no ordinary-PQ real-Chain end-to-end PASS and no authenticated-v1 runtime qualification from this failed run. Existing scoped test passes retain their original source/test scopes.

The candidate must remain **BLOCKED for this full-path qualification** with the existing budgets. No limit increase, packet cropping, compressed alternate handoff, reduced work profile, or test change is included in this review.

