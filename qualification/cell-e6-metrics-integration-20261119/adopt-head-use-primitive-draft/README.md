# Independent cold-use primitive — source draft for review

**Status: isolated source draft, not compiled, tested, installed or published.** This directory is separate from the original NoUpdate/cold-D composition. It contains real Rust implementations of a bounded wire format, strict decoder and a default-disabled relative signature verifier. No `mod` declaration, Cargo dependency, original source or product entry has been changed.

## What is implemented in the draft

| Source | Lines before formatting | Responsibility |
|---|---:|---|
| `owner_cold_use_wire.rs` | 326 | All 68 fields from the frozen wire design; fixed purpose, canonical signing bytes, subject/policy cycle separation, structural refusal, 16 KiB bound and complete signed-record digest |
| `owner_cold_use_decode.rs` | 136 | Bounded binary decoding, original StableId grammar, exact integer/digest/tag lengths, trailing-byte refusal and exact canonical re-encoding |
| `owner_cold_use.rs` | 187 | Explicit default Disabled; exact full expected-binding comparison; policy/subject/trust/role/epoch/time checks; original strict head signer verification; private relative fact with DENY_ALL |

The two data modules are children of the proposed private `owner_host::cold_use` module. The verifier reuses the original parent's `head_signers`, `verify_signer_context` and `verify_signature`, rather than inventing a signing key or a weaker verifier. The existing crate already depends on `ed25519-dalek` and `codex-hepta-types`; no dependency change is proposed. `Digest32::of_bytes/of_parts` is the existing SHA256 implementation. ID framing uses the original u64 big-endian length and original 128-byte StableId grammar.

The wire domain is `hepta.learning-artifacts.cold-task-use-grant.v1`. The record is the complete canonical preimage followed by the 64-byte signature. Its digest follows the previously frozen design exactly, including the separate leading purpose before the complete signing preimage. There is no JSON decoder or permissive transport fallback in this layer.

## Why this cannot enable production use

`ColdUseSignatureVerifierV1` and its enrollment state are private. `Default` constructs `Disabled`; there is **no public or parent-visible enrollment constructor**, configuration switch, default key, producer signer, private-key custody or production issuer. `RelativeOnly` is private data for future component fixtures and relative verification. It does not claim to be an installed authority policy. No `allow(dead_code)` or other gate suppression has been added to make this unwired draft appear integrated.

`expected`, the policy snapshot and the time arguments in this layer are deliberately relative inputs. A signature over them is not proof that C completed, that a file was read, that a policy was genuinely installed, or that the clock/revocation source is current. The returned private fact has `AuthorityPosture::DENY_ALL`, no capability conversion, no Clone/Deserialize/Send/Sync and no product consumer. A production implementation must obtain original owner inputs through the separate scoped APIs in the design; it cannot hand this function a peer-controlled verifier and treat the result as authorization.

The policy is initially stricter than a broad recipient allow-list: it permits one complete pre-selection subject digest. That digest covers all original Artifact, completed-C, D-recipient/run/operation/target, withdrawal and AuthBus fields. It excludes only the earlier policy/nonce/grant-ID/head-issuer/time header, avoiding a policy-digest recursion. The policy separately binds the original owner trust, head signer/key, epoch range and validity window. Full expected-object equality still binds every one of the 68 fields, including the nonce, grant ID and times.

The source self-review found and corrected a construction dependency in the first draft: deriving the subject had called the full-header validator, which required a nonzero policy digest before the policy could be computed. The current draft validates the subject independently; complete signing bytes still require both the original header and subject checks. No placeholder policy digest is needed. Initial source bytes and hashes remain under `revisions/01/`.

The default-off primitive needs no real private key or production custody to be written and reviewed. **Production enrollment, authenticated policy/revocation delivery, signing/custody, nonce persistence, historical physical reads, independent Selector V2 and Root/generation/live integration remain unimplemented.** They are not simulated by this draft. Generic expired CURRENT, V1 selection, Artifact writer behavior and the old 240/300-second rules are untouched.

## Small review/PR boundaries

The original `AGENTS.md` at `2b8125e3` has Git blob `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a`, SHA256 `c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480`. It asks complex changes to stay below 500 changed lines, encourages separate modules and requires separate `*_tests.rs` test files. No more-specific AGENTS exists at `codex-rs/`, this crate, or its `src/` in that exact source; the three 404 responses are retained in the base inventory.

These are **three dependent review stages**, not a claim that all 649 lines plus future tests fit one small PR:

1. **Wire data and canonical bytes.** The 326-line module, separately authored encoding controls and a narrow test-only harness. It grants no policy or authority. Measure the final diff including tests before publishing this stage.
2. **Bounded decoder.** The 136-line module, truncation/tag/length/canonical refusal controls, dependent on stage 1. No authority route.
3. **Default-disabled relative verifier.** The 187-line module, separate role/policy/signature/time/default-denial controls, dependent on stages 1–2. The only enrollment construction allowed at this stage is inside explicit component test fixtures. A production enrollment API requires its own original-authority review and is not part of these stages.

There is no product caller to update in these stages. A later test harness may privately declare these modules for component checks; it must not install an enabling production constructor to eliminate unused-code warnings. The final staged diff must include meaningful tests within the AGENTS size guidance; split further if it exceeds the limit. This draft has no test file yet because the present assignment authorizes source preparation and a component-control plan, with no native execution.

`just fmt`, `just test -p codex-hepta-learning-artifacts` and required scoped `just fix` are **pending**, not represented as passes. No Rust parser/compiler/native command was run. The only executed checks here are local generation, JSON decoding, source-field inventories and byte/hash readback. `COMPONENT_CONTROL_PLAN.json` distinguishes proposed primitive checks from the 34 broader product controls, all still unexecuted.

## Inputs and provenance

`BASE_READOUT.json` pins the exact AGENTS, crate manifest, Digest32 and StableId sources. Original owner/selector sources remain pinned in the separate design's `SOURCE_BINDINGS.json`. `DRAFT_INVENTORY.json` pins these three generated Rust files, the original `2b8125e3` source and the exact `WIRE_CONTRACT.json` SHA256. `build_source_draft.py` refuses another wire design hash; it generates source files only and never invokes a compiler, signer, model or remote owner.

This layer intentionally does not claim any of the 34 whole-design controls passed, any new grant was signed, or any cold D/FinalUse path ran.
