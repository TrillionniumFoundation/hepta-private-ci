# Cross-UID fixture and original custody audit

This is a read-only source audit of canonical cc57 and the fixed Root86 proposal. It does not change any source, permission, runtime budget, control, ref, or test.

## Result

A UID-60001 `VersionFixture::new_initial` creates explicit test-only file custody. It does not construct production Root CURRENT. The production Current constructors require a validated `RootAuthorityDirectory`, whose public opener requires UID 0 and protected root-owned paths. A UID-0 issuer connection alone does not bridge this missing Current owner.

FinalUse has two separate roles. `FinalUseAuthority` is the consumer and keeps nonce state private to its effective UID. `HostFinalUseIssuer` is the Root signing service and requires actual Root key custody and an independently valid lease. It need not reopen the consumer's nonce directory. An existing UID-60001 nonce directory cannot simply be reopened as UID 0.

## Why CURRENT is an owner dependency

The retained Version factory consumes `Arc<NeuronGenerationCurrentOwnerV1>`. Preparation loads CURRENT and CASes its intent; publication CASes the current generation inside the original grant-dispatch boundary. Retained and recovery paths continue reading that same Current owner, with Artifact and FinalUse checks. A path or initial snapshot cannot replace this dependency.

## Narrow B fixture separation

The B helper reads exactly four objective fields from the original RunStart record:

| Field | Type |
| --- | --- |
| snapshot.objective_digest | Digest32 |
| objective_semantic_bytes | Vec<u8> |
| objective_function_v1_digest | Digest32 |
| objective_function_v1_bytes | Vec<u8> |

A test-only borrowed objective view can remove that opaque SourcePublication parameter coupling. It must preserve B's independent actual source/Cell work and all evidence/qualification checks. A separate original A-to-Material binding must remain, including the original source and completed-task history, with actual authenticated D/T receipts. Trust cannot be supplied by a child's self-description.

## Evidence and limits

`SOURCE_INPUTS.json` binds 28 actually retrieved original bodies and 5 Root86 bodies whose complete bytes match the frozen overlay. `REVIEW.json` lists the exact source objects, factory use points, preserved checks, and remaining custody requirement.

This audit ran no H operation, compiler, formatter, QA method or gate. It proves neither successful cross-UID composition nor production usefulness. The frozen 51-path registration package is unchanged; its separate QA dual-baseline wording correction is in placement 79aa518b8c9aa15863ce1a618ab11f04271e4ca1.
