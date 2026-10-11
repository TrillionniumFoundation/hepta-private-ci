# Lane A documentation and claim-boundary policy

## 1. Document roles and precedence

Lane A uses four non-interchangeable document roles:

| Role | Location | Meaning |
| --- | --- | --- |
| Current executable contract | `docs/lane-a-foundation/<module>/...` | What checked-in source implements now |
| Target architecture | `docs/modules/<module>/TECHNICAL.md` | Desired ownership, contracts and future composition |
| Target implementation dossier | `qualification/module-execution-dossiers/detail/<module>.md` | Planned APIs, tests and delivery envelopes |
| Executed evidence | exact-candidate receipts and native CI artifacts | What was actually run for one source/tree |

For a question about current behavior, the current executable contract and
checked-in source take precedence over target prose. A target signature, domain,
component or work package is not a native capability until it appears in the
truth matrix and capability evidence map with source and test anchors.

## 2. Forbidden implications

The following implications are invalid:

- source exists -> production caller exists;
- tests exist -> independent acceptance exists;
- an in-memory model -> durable recovery exists;
- a digest field -> cryptographic verification exists;
- evidence was stored -> execution, promotion or release was authorized;
- secret metadata was observed -> secret ownership moved into Hepta;
- a target dossier names an API -> the API exists;
- a receipt from another SHA/tree -> the current candidate passed.

## 3. Current/target wording rule

Current documents use present tense only for source-backed behavior. Future or
unimplemented behavior must be under `Target-only design` and use explicit
future/target wording. Target guides may describe the desired architecture, but
their introductory status does not override this policy.

## 4. Capability traceability rule

Every entry in `currentCapabilities` has exactly one stable capability ID in
`CAPABILITY_EVIDENCE_MAP.json`. Each entry must bind:

- public symbols;
- exact source anchors;
- at least one positive test;
- at least one negative test;
- durability class;
- activation state;
- production caller or explicit absence;
- exact-candidate receipt status.

The verifier rejects missing, duplicate, mismatched or unsupported mappings.

## 5. Closure vocabulary

`closed` in this directory means only the named repository-controlled
documentation or drift obligation is closed at an exact source. It never means
all target architecture, external evaluation, production activation, operator
acceptance, promotion or release is complete.

External or independently governed gates cannot be self-issued by repository
source. They remain explicit rather than being converted into optimistic
booleans.
