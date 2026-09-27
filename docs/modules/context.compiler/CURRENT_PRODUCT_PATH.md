# context.compiler current product path
<!-- GENERATED CURRENT STATE: edit CURRENT_STATE.json; detailed design is retained separately. -->

State SHA-256: `734e7ba75c5242ef8a7488ad517369ff6602422a26b12c09346f723b589b020c`. Source anchor: `c21a781119e9fc241197b61a304698f023c8979b`.
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

- Earlier direct-source follow-up added the Responses developer/input_text slot guard and before-await exact observer reservation, plus exclusive expiry checks. Those changes and their nineteen unexecuted Rust regressions are retained.
- Agentd now reserves one preparation per turn before tokenizer await; concurrent preparation and unresolved durable attempts cannot authorize another physical send. Cancellation releases only the pre-commit reservation.
- Tokenizer stdin, stdout and exit share a deadline. Input and bounded output progress concurrently; errors kill the child and bound the cleanup wait. Cancellation retains kill-on-drop rather than claiming guaranteed synchronous reaping.
- Tokenizer executable and vocabulary require externally supplied expected SHA-256 pins. Configuration freezes after first successful load, artifacts are streamed through SHA-256 and rechecked around execution. Immutable interpreter/runtime and replace-and-restore qualification remain open.
- After tokenization, Agentd reads the current registry again and holds the same registry lock through exact proof construction and durable pre-send authorization. Expiry and wall-clock rollback are checked before authorization and expiry is checked after fsync. Post-authorization transport cancellation is not silently claimed.
- The Agentd final framing verifier also requires exactly one complete developer/input_text context string and rejects recursive duplicate JSON keys, wrong context roles, metadata-only placement and context concatenation.
- Durable schema 2 separates nonfinal observations from final receipts; Indeterminate remains unresolved across reopen, monotone final observations retain unknown history, and semantic retries do not depend on a later callback timestamp. New observations retain canonical provider receipt data; legacy digest-only history is not promoted into authenticated evidence.
- An uncertain post-rename directory sync fences the exact-delivery store until reopen; poisoned mutexes are not silently recovered. New owner errors expose only stable reason codes in Display and Debug.
- Compiled context is shared by Arc instead of repeatedly copying raw payloads. This is a source-level allocation reduction, not a measured target-host performance result.
- Twenty-one additional Rust regression functions are registered in the active Agentd module, including real signed-registry revocation during a child-process barrier, expiry, concurrent preparation, durable migration and failure fencing. Native execution is not asserted.
- The existing read-only exact-head and deterministic synthetic-merge workflows remain in place. No source repair script or workflow write-back is added by this runtime follow-up.

## 3. Current product call path

```text
current registry/optimizer path (provisional admission remains open)
  -> compile_prompt_registry_v2 -> compile_v2
  -> compiler-owned canonical bundle -> build_attachment
  -> Agentd staging (shared compiled context)
  -> Core/codex-api exact encoded HTTP body
  -> extension typed-slot guard and exclusive observer claim
  -> Agentd exclusive per-turn preparation reservation
  -> frozen artifact pins + bounded concurrent tokenizer I/O
  -> current registry re-read after tokenizer completion
  -> registry lock: current preparation + final proof + durable pre-send
  -> post-fsync exclusive expiry check -> same-body transport
  -> canonical provider observation -> schema-2 durable outcome
```
The durable authorization commit is the registry-revocation linearization point.
No await occurs while that registry lock is held. Revocation after authorization
still needs the transport owner's final-use/cancellation policy. Indeterminate
remains nonfinal and blocks blind replay; complete post-crash proof restoration
and independent terminal acknowledgement remain open. Dormant V3 files do not
count as current product composition.

## 4. Dormant integration inputs

- `codex-rs/hepta-prompt-registry/src/context_authority.rs`: Registry-owned V3 authority is still not registered by the crate root; it is not active merely because its file exists.
- `codex-rs/hepta-intelligence/src/prompt_product_v3.rs`: V3 materialization is not yet the current compiled product path.
- `codex-rs/hepta-agentd/src/prompt_product_v3.rs`: The active Agentd path remains prompt_runtime plus exact_context_delivery; no second delivery owner was activated.

## 5. Remaining implementation and qualification gates

- Complete and compile direct V3 authority/product integration and default-off legacy gating. This runtime follow-up does not activate the dormant V3 files or run source-migration scripts.
- Replace provisional product-owned admission with independently controlled registry/authority capabilities; the post-tokenization registry re-read is not independent admission authentication.
- Provision and independently qualify the real provider/model tokenizer, immutable executable/interpreter/runtime, vocabulary and normalization. Hash pins detect observed artifact drift but do not exclude adversarial replace-and-restore or attest semantic token accuracy.
- Integrate the transport owner final-use token and cancellation policy with the documented durable authorization linearization point. The registry lock prevents pre-authorization revocation races, not every revocation after a committed authorization.
- Complete post-crash reconstruction/verification of opaque preparation and final-request proofs and independently authenticated late-terminal reconciliation. Digest-only unresolved pre-sends still return RecoveryRequired rather than being fabricated into a delivered receipt.
- Bind terminal acknowledgement to exact attempt identity before reusing the turn observer. An identity-free encoded terminal callback is not independent reconciliation.
- Finish cross-holder raw-content redaction, remaining provider typed slots and full provider-framing policy qualification; the active profile remains developer-only.
- Qualify durable filesystem ownership, rollback resistance, symlink/race resistance and safe retention/retirement beyond bounded JSON state. Schema-2 rollback requires a compatible backup plus external-attempt reconciliation, never deletion of unresolved claims.
- Run pinned Rust formatting, compilation, all native regressions, affected product E2E, strict lint, dependencies and full source/document checks on the final exact source and merge objects. Local source checks do not establish native execution.
- Measure named-host p50/p95/p99, allocation and peak memory, concurrent admission, cold/warm tokenizer and long-lived recovery/backlog capacity.
- Obtain independent security acceptance and operator-controlled activation/release; repository source changes grant none of these authorities.

## 6. Verification

The prior follow-up recorded 20 local Python tests; that historical result is not native qualification for this commit. This runtime follow-up adds 21 Rust regression functions (40 across the two follow-ups), none executed locally. The original owner and all six new/changed runtime source blobs were verified against Git object identities; a local patch whitespace check passed. Generator/unit-test execution is documented separately in RUNTIME_FOLLOWUP_20260927.md. No Rust toolchain, complete workspace build or target-host measurement was available locally.

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
