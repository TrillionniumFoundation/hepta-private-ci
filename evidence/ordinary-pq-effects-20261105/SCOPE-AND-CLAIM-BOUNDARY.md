# Ordinary PQ effects: scope and claim boundary

Date: 2026-11-05. Status: **170 selected native tests passed; the real ordinary PQ → Chain case failed at the unchanged payload limit. Full-path qualification is BLOCKED and whole-chain PQ security remains HOLD**.

Reviewed pins: Hepta base `1556a4df6e279055fd8196f81a4ca2fe0f19384a`, implementation `ee57cd57c322a8fecdf674a662c741452baf6478`; Chain comparison base `a16a89f92a0db5ff6af9c1d7790f201841f079aa`, inspected integration candidate `7ae0d1b227853fc75e02334b497f69dd52d50235`. These are source identities, not deployment identities. Actual native commands and results are recorded separately in [the evidence index](README.md); source and deployment identities remain distinct.

## Concrete closure and exclusions

At the Hepta base, [ordinary inference][h-infer-base] required explicit `ml_dsa65_v2`, while the [configured PoN effects loader][h-effect-base] accepted a 32-byte verifier and selected [the compatibility constructor][h-constructor-base]: classical authority, system time, no external rollback oracle. Source reachability establishes the mismatch; this review does not claim an exploit replay against the complete native deployment.

The [new ordinary HTTP/PoN loader][h-loader] requires schema 4, explicit PQ profile, pinned ML-DSA-65 contract and issuer keys, authenticated revocation feeds, protected time and an existing external frontier. Grant, feed and contract epochs must agree; grant expiry cannot exceed feed expiry. The [versioned contract attestation][h-contract] preserves legacy signing bytes and privately records the algorithm actually verified. The [driver][h-driver] now requires a PQ lease in production and checks it before both dispatch and worker entry; the classical variant exists only under `cfg(test)`.

This closure is limited to ordinary automation effects. The separate [one-shot Browser product caller][h-browser] still passes a 32-byte key to `open_state_dir`. HTTP transport authentication and provider receipts do not become PQ merely because the local contract attestation does.

## Seven security objects

| Object | Fixed source examined and this branch's boundary | Evidence still required |
| --- | --- | --- |
| Accounts and transactions | Chain [account execution][c-account] checks authority generations, retained key history and nonce floors; [migration inventory][c-inventory] explicitly leaves external debts and source finality unresolved. This Hepta branch changes neither component. | Native rotation/migration executions preserving prior liabilities, nonce history and source retirement; recovery and reorganization adversarial cases with independently selected source checkpoints. |
| Tasks and evaluation | [NPQ5 task eligibility][c-task] resolves requester/source authority from actual state and verifies the bound statement; [NPQ6 evaluator code][c-evaluation] preserves historical round authority for conflict evidence. The Hepta change binds local effect intent and grants, not these Chain roles. | Composed tests showing current requester/source permissions, retired-key denial, evaluator accountability and real task effects across renewal, migration and restart. Signature validity alone is insufficient. |
| Software and protocol upgrades | Chain's [PQ release kernel][c-release] separates offline root, node software and protocol configuration roles, checks thresholds/versions, and requires pinned recovery checkpoints. No installer or governance activation is changed here. | Actual installer consumption of durably committed authorization, provisioned root custody, old/new quorum rotation, revoked-key rejection and recovery on deployed binaries/configuration. |
| Cell publication and adoption | The same [release kernel][c-release] separates manifest publication from activation and checks current root generation and publisher lifetime. This branch changes ordinary effect FinalUse, not the Cell adoption pipeline. | Trace immutable weights and manifest through activation, revocation, CURRENT and final consumption; prove fresh authority after rollback. A release observation or inference PQ gate alone does not qualify that entire path. |
| Network | [PNQ2][c-network] uses ML-DSA authentication and bounded replay state over loopback plaintext; its inspected blob is unchanged from the [comparison base][c-network-base]. The [mTLS C probe][c-mtls] is an independent experiment, explicitly [not a Rust listener integration][c-mtls-scope]. No listener is changed here. | Real listener wiring and independent peers, identity provisioning/rotation, replay and downgrade refusal, availability measurements. Public weights require authenticity/integrity; private tasks additionally require PQ confidentiality. Hybrid KEM key agreement does not replace peer identity authentication or current application authorization. |
| Recovery | Hepta composes its existing nonce/head owner with external clock/frontier services. Chain's [checkpoint store][c-checkpoint] compares complete journal count and root; [PNQ2 witness][c-witness] covers three network tables, not Hepta consumed grants or provider receipts. No Chain recovery code changes here. | Independent custody and freshness outside restored state; whole-owner cold rollback, uncertain CAS replies, power loss and receipt reconciliation. A frontier or expected root read from the restored files cannot certify those files' freshness. Rolling every witness back together leaves no independent evidence. |
| PoN consensus | [Required-work and retarget arithmetic][c-consensus] and the [whole-chain claim guard][c-hold] retain separate boundaries. This branch changes no work relation, difficulty rule or fork choice. | Quantum cost analysis for the cheapest complete valid work, reversible oracle/uncompute, data access and challenge amortization; adversarial retarget, reorganization and propagation evidence under comparable budgets. **Quantum useful-work assumptions remain HOLD; no PQ-128 conclusion follows from ML-DSA tests.** |

## Test evidence that this patch can support

The [seven Agentd test sources][h-tests] exercise ordinary loading with real ML-DSA signatures and signed Unix clock/frontier fixtures. They specify one wiremock HTTP dispatch with exact stable identity, terminal receipt readback after reopen and later revocation/expiry/service loss, valid legacy V1/V3 rejection before trust contact, invalid/expired feeds, grant lifetime bounds, denial of replayed older signed feeds and frontier unavailability.

The head-change test manually constructs the original store driver; it does not independently schedule a race inside ordinary `execute`. Mandatory production lease typing closes the previous optional-lease omission shape. Removing only the second worker check still lacks a dedicated counterfactual test. These are coverage limits, not observed failures.

Terminal readback after service loss is qualified only after the ordinary host has opened successfully. The tests reopen while the clock/frontier answer and subsequently remove their availability. Cold startup still requires those services; no successful cold startup during a trust-service outage is claimed.

The two ordinary PoN cases have different scopes and separate execution records:

| Case at the implementation pin | Intended evidence | Native execution status in this document |
| --- | --- | --- |
| Original [schema 4 loader case][h-tests] | Opens an inert real ELF and namespace marker; checks contract tampering. It executes no Chain business logic and proves no settlement. | **PASS at `ee57cd57`**, in the 38-test ordinary effect group; only loader/contract construction is qualified by this case. |
| Added [real Chain continuation][h-chain-tests] | Ordinary loader → AutomationStore → original sealed PoN adapter → actual Node, on both backends; stable identity, nonce 1, exact receipt readback after reopen and provider unavailability. | **FAIL / qualification BLOCKED at `ee57` + `04be`**: 1 run, 0 passed, 1 failed, 259 skipped; both original attempts stop at 49,508 > 24,576 bytes, before PQ host construction on the first `legacy-v2` iteration. `authenticated-v1` and subsequent dispatch/recovery assertions were not reached. |

The [native-pair workflow][h-pair-ci] previously selected [real Chain adapter][h-pair-tests] and [signed-task adapter][h-pair-task-tests] cases that bypass ordinary loading and AutomationStore. Its new required step selects the added ordinary case with the original source-pair pins and budgets, including ordinary Agentd's stricter 24-KiB wire limit. The [source size proof](TRANSPORT-BLOCKER.md) shows that 49,508 bytes is the original codec's minimum complete packet, including zero transactions; the existing hex RPC also exceeds its control-frame budget. This failing required gate remains in the Draft PR. The workload retains legacy Chain task/evaluation profiles. Local signed fixture services establish neither independent custody nor deployed PQ Chain authority.

The expanded CI scan covered all 88 workflows, 44 executable CI scripts, 14 action files, 103 inference-host Rust sources, its sole integration test, 38 executable qualification sources and 9 QA files. No additional legacy schema 1/3 effect-config generator was found. Final-pin tree comparison preserves that result: the sole workflow change is this new scoped step. Exact scan provenance, limits and commands are in [CI entrypoint review](CI-ENTRYPOINT-REVIEW.md).

Promotion requires separately retained results tied to the final source/lockfile, commands, actual endpoints and fault conditions. The four successful scoped runs and the failed real-Chain continuation are retained with those identities. None supplies deployed end-to-end PQ security; the latter proves a concrete blocker that must be resolved under a separately reviewed interface/protocol design.

[h-infer-base]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1556a4df6e279055fd8196f81a4ca2fe0f19384a/codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs
[h-effect-base]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1556a4df6e279055fd8196f81a4ca2fe0f19384a/codex-rs/hepta-agentd/src/automation_effect_host.rs
[h-constructor-base]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1556a4df6e279055fd8196f81a4ca2fe0f19384a/codex-rs/hepta-contracts/src/final_use.rs
[h-loader]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq.rs
[h-contract]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/model-provider/src/provider_effect_pq.rs
[h-driver]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host.rs
[h-browser]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs
[h-tests]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq_tests.rs
[c-account]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2.rs
[c-inventory]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2/migration_inventory_v1.rs
[c-task]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2/tasks_v5.rs
[c-evaluation]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-mvcc-fee/src/pon_executor/pq_accounts_v2/application_v6.rs
[c-release]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-release-bundle/src/pq_release.rs
[c-network]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-pon-node/src/ingress/pq_network.rs
[c-mtls]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/formal/pon-nakamoto-v1/pq_mtls_probe.c
[c-mtls-scope]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/docs/security/PQ_PEER_MTLS_RESEARCH_V1.md
[c-checkpoint]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-checkpoint-store/src/lib.rs
[c-witness]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-pon-node/src/pq_rollback_witness.rs
[c-consensus]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/trillionnium/crates/trnm-pon-node/src/consensus.rs
[c-hold]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/7ae0d1b227853fc75e02334b497f69dd52d50235/docs/security/WHOLE_CHAIN_PQ_CLAIM_GUARD_20261031.md
[c-network-base]: https://github.com/TrillionniumFoundation/Trillionnium-Chain/blob/a16a89f92a0db5ff6af9c1d7790f201841f079aa/trillionnium/crates/trnm-pon-node/src/ingress/pq_network.rs
[h-pair-ci]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/.github/workflows/hepta-pon-native-pair.yml
[h-pair-tests]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pon_chain_tests.rs
[h-pair-task-tests]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pon_task_chain_tests.rs
[h-chain-tests]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ee57cd57c322a8fecdf674a662c741452baf6478/codex-rs/hepta-agentd/src/automation_effect_host_pq_chain_tests.rs

