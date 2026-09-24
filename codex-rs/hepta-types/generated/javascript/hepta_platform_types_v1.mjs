// GENERATED from bindings/PLATFORM_TYPES_BINDINGS_V1.json; DO NOT EDIT.
const SPEC = {"schema":"hepta.platform-types.generated-bindings.v1","schemaVersion":1,"stableIdMaxBytes":128,"idProfiles":[{"variant":"Stable","id":"stable-v1"},{"variant":"Module","id":"module-v1"},{"variant":"Namespaced","id":"namespaced-v1"},{"variant":"Execution","id":"execution-id-v1","prefix":"execution:"},{"variant":"Schema","id":"schema-id-v1","prefix":"schema:"},{"variant":"Normalization","id":"normalization-id-v1","prefix":"normalization:"},{"variant":"Receipt","id":"receipt-id-v1","prefix":"receipt:"},{"variant":"Artifact","id":"artifact-id-v1","prefix":"artifact:"}],"authorityWireV1":{"encodedBytes":1,"trustedMask":0,"bits":{"runtime":0,"productionWriter":1,"modelInvocation":2,"providerDispatch":3,"externalEffect":4,"selection":5,"promotion":6,"release":7}},"fixedQ32":{"scale":"4294967296","arithmeticProfileId":"fixed-q32-toward-zero-v1","multiplyDivideRounding":"toward-zero"},"numericProfiles":[{"id":"hnmf-ppm-toward-zero-v1","version":1,"scale":"1000000","rounding":"toward-zero"},{"id":"signed-q24-nearest-ties-even-v1","version":1,"scale":"16777216","rounding":"nearest-ties-even"},{"id":"signed-q32-nearest-ties-even-v1","version":1,"scale":"4294967296","rounding":"nearest-ties-even","sharesFixedQ32RawScale":true,"fixedQ32ArithmeticCompatible":false}],"canonicalDigestV1":{"magic":"HPTC","encodingVersion":1,"domain":"hepta.platform.types.canonical-digest.v1","maxEncodedBytes":262144,"maxContainerItems":4096,"maxDepth":16}};
const UTF8 = new TextEncoder();
export const STABLE_ID_MAX_BYTES = SPEC.stableIdMaxBytes;
export const ID_PROFILES = Object.freeze(Object.fromEntries(SPEC.idProfiles.map((row) => [row.variant, Object.freeze(row)])));
export const AUTHORITY_WIRE_V1 = Object.freeze({...SPEC.authorityWireV1, bits: Object.freeze({...SPEC.authorityWireV1.bits})});
export const FIXED_Q32 = Object.freeze(SPEC.fixedQ32);
export const NUMERIC_PROFILES = Object.freeze(Object.fromEntries(SPEC.numericProfiles.map((row) => [row.id, Object.freeze(row)])));
export const CANONICAL_DIGEST_V1 = Object.freeze(SPEC.canonicalDigestV1);

export function numericProfile(profileId) {
  if (typeof profileId !== "string" || !Object.hasOwn(NUMERIC_PROFILES, profileId)) {
    throw new Error("unknown numeric profile");
  }
  return NUMERIC_PROFILES[profileId];
}
export function admitAuthorityWireV1(raw) {
  if (!(raw instanceof Uint8Array) || raw.length !== AUTHORITY_WIRE_V1.encodedBytes) throw new Error("authority wire V1 must be exactly one byte");
  if (raw[0] !== AUTHORITY_WIRE_V1.trustedMask) throw new Error("authority grant bits are not representable by platform.types");
}
export function validateIdProfile(value, variant) {
  const encoded = UTF8.encode(value);
  if (encoded.length === 0 || encoded.length > STABLE_ID_MAX_BYTES || value.includes("\0")) throw new Error("identifier bound");
  if (typeof variant !== "string" || !Object.hasOwn(ID_PROFILES, variant)) throw new Error("unknown identifier profile");
  const row = ID_PROFILES[variant];
  if (variant === "Stable") {
    if (!/^[A-Za-z0-9._:-]+$/.test(value)) throw new Error("stable identifier grammar");
    return value;
  }
  if (variant === "Module") {
    const parts = value.split(".");
    if (parts.some((part) => !/^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$/.test(part))) throw new Error("module identifier grammar");
    return value;
  }
  let local;
  if (variant === "Namespaced") {
    const parts = value.split(":");
    if (parts.length !== 2) throw new Error("namespaced identifier grammar");
    validateIdProfile(parts[0], "Module");
    local = parts[1];
  } else {
    if (!row.prefix || !value.startsWith(row.prefix)) throw new Error("profile prefix");
    local = value.slice(row.prefix.length);
  }
  if (!/^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$/.test(local)) throw new Error("profile local identifier grammar");
  return value;
}
