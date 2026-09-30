# utility.ndu status and claim boundary

Status: **one unified source candidate; exact-head and synthetic-merge qualification pending for the current PR head; production activation false**.

This page is the short interpretation guide for `utility.ndu`. It does not grant effect authority, production acceptance, model promotion, signing authority, release authority, or permission to reinterpret source presence as deployed evidence.

## 1. Unique candidate topology

The only current integration line is:

```text
main@a126987b84737dbc2ee2592442a314117bddb4a2
  -> #1140 A-D hardening, durable owner/store, recovery and qualification infrastructure
  -> #1206 bounded deterministic FBSDE training candidate
  -> #1221 authority, replay, artifact-catalog, migration and production-contract hardening
  -> work/utility-ndu-unified-candidate-20260930 / PR #1225
```

The integration merge retained the stronger #1140 journal predecessor-CAS, revocation-capacity reservation, context-bound iteration receipt, authenticated owner and durable-store semantics wherever #1221 carried a narrower parallel implementation. It imported the #1221 V2 projection catalog, hierarchy/artifact hardening and production-contract work, then added authenticity, additive compatibility, current-use and independent-learning gates.

No qualification receipt from #1140, #1206 or #1221 is inherited. Every new commit invalidates the previous candidate result. Current source truth is the head of PR #1225 plus its exact tree and the source objects recorded by `IMPLEMENTATION_MAP.json`, `IMPLEMENTATION_MAP_EXTENSIONS.json` and `IMPLEMENTATION_MAP_UNIFIED.json`.

## 2. Status axes remain independent

- `TECHNICAL.md` defines the stable architecture, ownership and work-package envelopes.
- The three implementation maps bind native operations, executable tests and exact source objects.
- `UNIFIED_CANDIDATE.md` records the integration and acceptance model for the current line.
- `PRODUCTION_HARDENING.md` defines the hardening gates.
- Workflow receipts establish only the exact source and deterministic merge identities they name.
- Target-host, external backup, restore, monitoring, independent stochastic acceptance, activation and release remain separate evidence domains.

A `source_implemented` or `candidate_implemented` value means that bounded source and tests exist. It does not mean that a production adapter is deployed, a writer is selected, a model is promoted or a release is authorized.

## 3. Current bounded capability

The current candidate contains:

- deterministic feasibility, policy-bound scoring and tolerant Pareto evaluation;
- bounded preference solving with validated termination and maximum-residual semantics;
- recursive utility, conditional moments, covariance regression and explicit Z-coordinate/Q24 conversion;
- semantic projection journal, predecessor-CAS replacement, scoped revocation and capacity reserved for revoking every live projection;
- crash-bounded `NduProjectionStoreV1`, authenticated owner composition, process bootstrap and real Agentd/Control caller paths inherited from the A-D line;
- additive projection-epoch/archive, recovery, retention and operational-observer candidates;
- bounded discrete FBSDE dataset admission, filtration checks, backward training, Q24 artifact sealing, independent reference recomputation and shadow-stage gates;
- projection catalog V2 with separate action and projection kind, durable artifact binding and explicit V1 migration;
- Ed25519-authenticated hierarchy and artifact receipts bound to key identity, trust revision, validity window, policy, current revocation epoch and current revocation-frontier digest;
- immutable locator V2 profiles that require either a content digest or an exact object version plus content digest;
- sealed iteration and Z-conversion V2 receipts that recompute canonical fields and migrate only after the corresponding V1 receipt is independently revalidated;
- a closed production-composition descriptor that requires concrete identities, implementation/configuration digests, policy revisions, deployment instance digests and capability receipts for every required adapter role;
- independent FBSDE evidence and deterministic rollback-trigger contracts.

All model, authenticity, migration, replay, current-use, readiness and learning receipts introduced on this line remain `DENY_ALL`. They are evidence objects, not effect grants.

## 4. Compatibility model

The public V1 source surface remains additive and readable:

- `NduIterationReceiptV1` retains its public fields and historical canonical digest contract;
- `ZQ24ConversionReceiptV1` retains its public fields;
- external-crate compile tests destructure both V1 types;
- `PUBLIC_API_BASELINE_V1.json` freezes field names and order;
- `hepta-ndu-public-api-compat.py` rejects in-place privacy, removal or reordering;
- V2 construction is sealed and V1-to-V2 migration fails closed when canonical recomputation differs.

V1 compatibility does not imply that a V1 binary may mutate a V2 store image. Store migration and rollback follow the explicit forward-only rules in `PRODUCTION_HARDENING.md`.

## 5. Historical replay is not current authorization

Identical operation replay resolves the historical terminal entry before mutable current-state checks. This preserves idempotent recovery after a lost response, including after a later revocation.

`NduHistoricalReplayReceiptV2` therefore proves only what a named operation previously returned. It is always `DENY_ALL` and cannot establish present eligibility.

`validate_current_use_v2` is a separate path. It requires the projection still to be selected, an authenticated artifact bound to the selected durable binding, trusted-time evidence, the current revocation frontier, artifact availability, a final-use grant binding and the current production policy. Revocation removes the selected artifact and causes current-use admission to fail even though historical replay remains available.

## 6. Production composition and its limits

`NduProductionCompositionV1` requires exactly one concrete binding for each closed role:

1. persistent projection store;
2. authenticated owner/writer;
3. process fence;
4. cross-host fence;
5. trusted time;
6. revocation frontier;
7. artifact registry;
8. encrypted remote backup;
9. restore executor;
10. metrics exporter;
11. real product caller.

A binding names the adapter ID, implementation digest, configuration digest, policy digest and revision, deployment-instance digest and capability receipt. A production-readiness receipt additionally requires exact-head, deterministic-merge, target-host/filesystem, shared-volume fencing, encrypted backup readback, restore drill, metrics-delivery, product-caller and independent stochastic-acceptance evidence.

The source type does not claim that those adapters are deployed. Missing or zero evidence fails closed. The readiness receipt remains `DENY_ALL` and does not activate production.

## 7. FBSDE claim boundary

The training path remains bounded shadow/advisory source. Independent acceptance requires all of the following to be non-zero, current and candidate-bound:

- registered immutable dataset and immutable-locator binding;
- filtration and leakage audits;
- independent numerical oracle;
- convergence envelope;
- calibration, utility-improvement and regression acceptance;
- minimum shadow episode and decision volume;
- advisory and restricted-write runtime receipts;
- named target-host receipt;
- deterministic rollback policy and a non-triggered current rollback receipt.

The independent acceptance receipt remains `DENY_ALL`, records `productionActivation=false`, and does not register, select, promote or release a model.

## 8. Qualification interpretation

The dedicated NDU workflow must execute source, core, caller, product, strict lint and host suites for both:

- the exact PR head; and
- a deterministic synthetic merge with the current base.

The separate public-API workflow performs the frozen V1 baseline, adversarial gate tests and external-crate compile test in both lanes. The cryptographic fixture gate, development-document gate, Lane-D semantic conformance and blocking CI must also pass on the same head.

A workflow definition, queued run, older green run or unchanged subtree is not a passing receipt. Only completed retained receipts naming the exact current SHA/tree and synthetic-merge parents may change the qualification fields from false.

## 9. Production closure remains open

Until retained external evidence exists, the following remain false:

- selected and enrolled production owner/writer composition;
- target production filesystem and shared-volume crash qualification;
- protected clock and independently persisted anti-rollback/revocation frontier;
- approved encrypted off-host backup transport and immutable readback;
- executed restore, retention and deletion drills;
- deployed metrics exporter, dashboards, alerts and operator runbook acceptance;
- cross-platform qualification where required;
- registered production training dataset and independent stochastic-policy acceptance;
- canary, promotion, production activation and release authority.

Hosted CI, mounted fault fixtures and source-level receipts cannot establish physical power-loss durability or external service deployment.

## 10. Safe claim language

Use:

- `unified utility.ndu source candidate`;
- `deterministic NDU with bounded FBSDE shadow candidate`;
- `durable-writer source candidate`;
- `authenticated evidence and composition contracts implemented`.

Do not use:

- `production complete`;
- `production writer activated`;
- `learned FBSDE policy accepted`;
- `release qualified`;
- `physical durability proven`.
