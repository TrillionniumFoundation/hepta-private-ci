# Hepta control UI

This source root contains the authority-free presentation core for `ui.control`.
It projects bounded runtime observations and constructs typed operation intents.
It neither issues authority nor writes an authoritative store directly.

The legacy object entrypoints remain compatibility surfaces and continue to
drop presentation-only fields from their outputs. The additive `Local` JSON
entrypoints are versioned, private-workspace internal exports for shadow
qualification. The export boundary is a repository convention, not JavaScript
enforcement. These entrypoints cap encoded input before parsing, require the
repository's lexicographic object-key order, reject duplicate, unknown, missing
or otherwise non-canonical fields, and return frozen primitive-only
projections. They are not registered module ingress or egress and have no
production caller. In particular, the local UI proposal is not
`OperationIntentV1`, which remains owned by `kernel.operations`; a registered,
separately authorized adapter must validate current state and construct that
contract.

`src/agentd_bridge.js` adds the narrow UI/Agentd module-port contract. A
trusted Agentd-owned adapter is injected with only `readRuntime` and
`submitProposal` methods. The bridge returns bounded runtime projections and
proposal-admission receipts; it never exposes the owner-only Agentd UDS,
credentials, HOS2 `D` identity, capability handles, or final-use grants.
`submitProposal` is deliberately not an effect executor: physical execution
and terminal confirmation remain with the canonical Agentd/operations owners.
The bridge is a contract adapter with test coverage, not a claim that a
production Agentd caller has already been composed.
