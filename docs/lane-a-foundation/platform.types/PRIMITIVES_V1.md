# Lane A primitive and shared-contract rules V1

## Identity

`StableId::new` preserves the compatibility grammar: nonempty UTF-8 restricted
to ASCII alphanumeric plus `.`, `_`, `-` and `:`, bounded to 128 encoded
bytes. It performs no case folding or Unicode normalization.

New protocol boundaries use `validate_id(raw, IdProfileV1)` before allocation.
V1 profiles are `Stable`, `Module`, `Namespaced`, `Execution`, `Schema`,
`Normalization`, `Receipt` and `Artifact`. The last five bind the literal
prefixes `execution:`, `schema:`, `normalization:`, `receipt:` and
`artifact:`. Cross-profile substitution rejects; profiles never normalize a
rejected identifier into an accepted one.

## Monotonic values

`Generation`, `Revision` and `LogicalSequence` are nonzero `u64`
newtypes. `next` is checked and rejects overflow. They are exact values and
are never passed through approximate numeric conversion.

## Authority boundary

`AuthorityPosture` and `NonAuthorizingPosture` are sealed deny-only values.
Neither can represent runtime, write, model, provider, effect, selection,
promotion or release authority.

`AuthorityFlagsV1` is an explicitly untrusted decode/testing shape. Raw V1
authority ingress is exactly one byte: `0x00` constructs deny-all; any nonzero
bit rejects in `AuthorityPosture::try_from_wire_bytes` before a trusted posture
exists. Actual authority tokens belong to `kernel.authority`, never
`platform.types`.

## Digests and canonical bytes

`Digest32` is exactly 32 bytes. Text parsing accepts exactly 64 lowercase hex
characters. `Digest32::ZERO` is a structural sentinel and is not evidence.

`canonical_encode_v1` / `canonical_digest_v1` own the frozen HPTC V1
structured commitment. The domain, type tags, integer widths, lengths,
field/map ordering, array order and capacity limits are frozen in
`CANONICAL_DIGEST_V1.md`. `canonical_validate_v1` validates supplied HPTC V1
bytes fail-closed, including bool/tag validity, canonical ordering, UTF-8,
depth/item bounds, truncation and trailing bytes. Successful validation grants
no authority.

V1 intentionally performs no Unicode normalization. NFC and NFD inputs remain
different bytes and different digests.

## Bounded values

`BoundedText<N>` and `BoundedBytes<N>` reject a zero maximum, empty input and
content larger than `N`; text additionally rejects NUL. Bounds count encoded
bytes. Borrowed preflight constructors validate before allocating the owned
copy.

## Immutable contract registry

`RegistryDefinitionV1` binds kind, profile-specific ID namespace, version and
bounded definition text into `canonical_digest_v1`. Schema definitions require
`schema:*`; normalization definitions require `normalization:*`.

`ContractRegistryV1` is a caller-owned immutable generation. It is bounded to
256 total definitions/profile definitions, 4096 UTF-8 bytes per ordinary
definition and 256 KiB aggregate ordinary-definition bytes. It rejects
duplicate identities and duplicate numeric profiles. It is not a global
registry, discovery system or authority source.

## Numeric-profile admission

`NumericProfileDefinitionV1` binds the exact native numeric profile identity,
definition version, scale and rounding rule to a canonical digest. V1 currently
admits only the exact semantics of:

- `hnmf-ppm-toward-zero-v1`;
- `signed-q24-nearest-ties-even-v1`;
- `signed-q32-nearest-ties-even-v1`.

Changing scale or rounding under the same V1 profile identity rejects.
`rescale_signal_registered` requires the source profile, target profile and
normalization digest to resolve in the same explicitly supplied immutable
registry generation. It returns `RegisteredNumericConversionReceiptV1`, whose
registry and admission digests are separate from the embedded pure arithmetic
receipt. Authentication/provisioning of that generation belongs to the product
owner and is a separate composition gate.

`utility.ndu::NduNumericRegistryV1` is the first named native consumer. An
`NduAuthenticatedOwnerV1` opened with that registry freezes the registry digest
into its production-policy identity before admitting a utility signal. An owner
opened without a registry cannot claim registered admission.


## Shared observation and topology contracts

`PromptDeliveryObservationV1` validates the physical delivery disposition,
provider-request digest, optional bounded strictly increasing token positions
and optional bounded rejection reason. Its semantic digest binds every field.
It is source-consumed by the Codex adapter/Agentd path and learning ledger.

`RuntimeTopologyCandidateV1` validates generation succession, rollback
predecessor, per-operation delta shape, split/merge participants and a candidate
digest recomputed from every implementation/evidence delta. Runtime Supervisor
checks it again against the current serving topology and independent selection
receipt before admission.

## Owned manifest contracts

`RandomStreamManifestV1` binds a nonzero root-seed digest, algorithm namespace,
episode/decision/stream IDs, a strictly increasing counter interval and exact
generator identity/version.

`ExternalSystemManifestV1` binds the closed system class, host/OS/package/
service/filesystem/identity/network/secret digests, a strict canonical UTC
observation time and nonzero authorization witness. It describes a supplied
observation; it does not scan a host.

`SensorCalibrationManifestV1` binds sensor identity/class, hardware or adapter
digest, nonzero generation, clock domain, increasing canonical UTC validity
window, bounded uncertainty profile, operating range and closed failure policy.
It validates calibration metadata; it does not operate a sensor.

All three use private fields, checked constructors, explicit `validate` and a
stable HPTC semantic digest. Their source implementation does not imply an
external JSON codec or runtime driver.

## Q32 semantic split

`FixedQ32` raw values use scale `2^32`, but its compatibility
`checked_mul`/`checked_div` arithmetic is explicitly
`fixed-q32-toward-zero-v1`. The numeric conversion profile
`signed-q32-nearest-ties-even-v1` has the same raw scale but a different
rounding contract. Raw-scale equality is therefore not arithmetic
compatibility. Explicit `checked_*_toward_zero` methods and profile metadata
make the distinction testable.

## Generated bindings and compatibility

`bindings/PLATFORM_TYPES_BINDINGS_V1.json` is the language-binding source
spec. `bindings/generate_bindings.py` deterministically emits a Python runtime
binding, JavaScript runtime binding and TypeScript declarations under
`generated/`. CI regenerates with `--check` and runs Python/JavaScript
consumer compatibility gates.

Generated bindings cover the frozen foundational identity/profile/authority
wire/numeric-profile/Q32/canonical constants. JavaScript profile/ID lookups use
own-property membership, so inherited names such as `constructor`, `toString`
and `__proto__` reject consistently with Python and Rust. Generated bindings do
not make arbitrary Rust domain structs into external schemas and do not
constitute product activation.

## Conformance

`CANONICAL_V1_CONFORMANCE.json` contains five accepted vectors and seven
rejection cases. Rust, Python and Node independently exercise accepted bytes
and malformed cases including duplicate fields/keys, zero schema, oversize,
depth overflow, invalid bool/tag and the explicit no-Unicode-normalization
contract. Exact-head and deterministic synthetic-merge workflow receipts remain
candidate-bound evidence.
