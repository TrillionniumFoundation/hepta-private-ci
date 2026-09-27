# context.compiler current product path
<!-- GENERATED CURRENT STATE: edit CURRENT_STATE.json; detailed design is retained separately. -->

State SHA-256: `9eecc73756742e66e2f69d81f3700eaf72cc65838a078f37df1a73c5e1ff9155`. Source anchor: `0acd6e0c9889e67beeb25e1b1885de6807daa3ca`.
The source anchor is provenance, not the final tested head. Only external execution receipts bind a final source/merge object.

## 1. Current implementation and evidence state

| Dimension | Current state |
|---|---|
| `sourceExists` | `true` |
| `compiledModuleReachability` | `partial` |
| `productCallPath` | `partial` |
| `exactHeadExecution` | `unverified` |
| `independentAcceptance` | `false` |
| `activation` | `false` |
| `release` | `false` |

## 2. Direct-source changes in this follow-up

- Responses context placement is checked in the actual exact-body observer before the host callback: one complete developer/input_text string, no metadata-only, wrong-role, schema-slot, duplicate-key, duplicate-occurrence, or concatenated-text acceptance.
- The observer reserves the exact attempt and request digest before await. Concurrent entry, cancellation during proof, poisoned state, and indeterminate/abandoned terminal observations do not re-arm dispatch.
- Exclusive attachment expiry is checked both before and after expensive host preparation. A post-preparation expiry refuses transport and leaves durable reconciliation to the existing owner.
- Nineteen Rust regression functions are present and registered, including 256 generated Unicode/control-string cases. Their execution is not asserted.
- Read-only source-head and deterministic synthetic-merge candidate tooling rejects dirty/substituted source, aliases, non-commit objects, duplicate or reordered parents, and source self-certification.

## 3. Current product call path

```text
current registry/optimizer path (provisional admission remains open)
  -> compile_prompt_registry_v2 -> compile_v2
  -> compiler-owned canonical bundle -> build_attachment
  -> Agentd prompt_runtime + exact_context_delivery
  -> Core / codex-api exact encoded HTTP body
  -> verify_responses_developer_context
  -> exclusive observer Proving claim (before await)
  -> host final-request proof / tokenizer / durable pre-send
  -> exclusive expiry recheck -> same-body transport
  -> provider terminal -> existing owner reconciliation
```
The structural slot guard is not an independent admission authority. The expiry
recheck is not a registry revocation check. Full late-terminal recovery and an
attempt-bound acknowledgement remain open. V3 files listed below are not
counted as active merely because they exist.

## 4. Dormant integration inputs

- `codex-rs/hepta-prompt-registry/src/context_authority.rs`: Registry-owned V3 authority exists as a file but is not yet registered by the crate root at the runtime source anchor.
- `codex-rs/hepta-intelligence/src/prompt_product_v3.rs`: V3 product materialization is not yet the current compiled product path.
- `codex-rs/hepta-agentd/src/prompt_product_v3.rs`: The active Agentd path still uses prompt_runtime plus exact_context_delivery; this file is not counted as active delivery.

## 5. Remaining implementation and qualification gates

- Complete and compile direct V3 authority/product integration and default-off legacy gating on this branch; dormant files and migration scripts are not implementation evidence.
- Replace provisional product-owned admission records with independently controlled current registry/authority verification.
- Provision and independently qualify immutable tokenizer binary, interpreter/runtime, vocabulary, normalization and provider/model interpretation; move stdin I/O inside the tokenizer timeout and close artifact replacement races.
- Revalidate revocation after tokenization at the durable send-authorization linearization point. The new expiry guard does not close the registry revocation race.
- Complete crash/reopen recovery of exact preparation/attempt evidence and independent late-terminal reconciliation; preserve nonterminal Indeterminate history and handle uncertain fsync with fencing.
- Bind terminal acknowledgement to exact attempt identity before permitting reuse of the turn observer; an identity-free terminal notification is not independent reconciliation.
- Complete raw-content Debug/error redaction across all holders and qualify typed slots beyond the current developer-only profile.
- Execute all native regressions, full affected product tests, strict lint, formatting, dependency and source/document checks on the final source and synthetic-merge objects.
- Measure named-host p50/p95/p99, allocation and peak memory, concurrency, cold/warm tokenizer and revocation races; no target-host performance is claimed.
- Obtain independent security acceptance and operator-controlled activation/release; repository changes do not grant these authorities.

## 6. Verification

20 local Python tests passed (14 real-Git candidate tests and 6 execution-summary parser tests). The 19 newly added Rust regressions were not executed locally. These numbers are not whole-module coverage or target-host qualification.

The canonical workflow uses separate source-head and deterministic synthetic-merge lanes. Both must retain passing receipts with source/base/tested commit/tree, run/attempt, command exit codes, nonempty native test counts and log digests. Candidate identity is revalidated before and after each command. Pending, skipped, cancelled and missing artifacts are not passes.

## 7. Retained detailed design

The complete previous technical guide, implementation map, dossier and product-path design are preserved byte-for-byte below. Their earlier completion statements are historical, not current acceptance evidence. Algorithms, proof objects, byte identities, capacity requirements, threat controls, migration targets and test design remain available in full.

- [TECHNICAL.md](design-baseline/TECHNICAL.md) — retained Git blob `ffe234853d9be0666ce1980607227a4b1f05997a`
- [IMPLEMENTATION_MAP.json](design-baseline/IMPLEMENTATION_MAP.json) — retained Git blob `ccd04f04efde519b7deaf020e49d631dc09ffdf2`
- [context.compiler.md](design-baseline/context.compiler.md) — retained Git blob `4cbb4f33e5ab1984ca851f3dcbb3c1c22b361f15`
- [CURRENT_PRODUCT_PATH.md](design-baseline/CURRENT_PRODUCT_PATH.md) — retained Git blob `3e0574772391b71b247c25514507826860543a83`
- [MODULE_MANIFEST.json](design-baseline/MODULE_MANIFEST.json) — retained Git blob `938477695f05fbf08818e3387f73964c1442c04a`

## 8. Change discipline

Edit `CURRENT_STATE.json`, run `python3 scripts/generate_context_compiler_module_docs.py --write`, and commit all five projections together. CI uses `--check` only. Source-navigation checks are deliberately not described as compilation or independent security acceptance. No candidate workflow may rewrite Rust source or push remediation commits.
