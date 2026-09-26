// Consumer compatibility gate for generated Platform Types JavaScript binding.
import {
  STABLE_ID_MAX_BYTES,
  AUTHORITY_WIRE_V1,
  FIXED_Q32,
  ID_PROFILES,
  NUMERIC_PROFILES,
  admitAuthorityWireV1,
  numericProfile,
  validateIdProfile,
} from "../generated/javascript/hepta_platform_types_v1.mjs";

if (STABLE_ID_MAX_BYTES !== 128) throw new Error("stable ID bound drift");
validateIdProfile("a".repeat(128), "Stable");
{
  let rejected = false;
  try { validateIdProfile("a".repeat(129), "Stable"); } catch (_) { rejected = true; }
  if (!rejected) throw new Error("generated JavaScript binding admitted a 129-byte StableId");
}
validateIdProfile("schema:numeric-signal", "Schema");
validateIdProfile("normalization:identity", "Normalization");
for (const [value, variant] of [["plátform.types", "Module"], ["platform.-types", "Module"], ["schema:naïve", "Schema"]]) {
  let rejected = false;
  try { validateIdProfile(value, variant); } catch (_) { rejected = true; }
  if (!rejected) throw new Error(`generated JavaScript binding admitted non-Rust identifier grammar: ${variant} ${value}`);
}
admitAuthorityWireV1(new Uint8Array([0]));
if (!Object.isFrozen(ID_PROFILES) || !Object.isFrozen(ID_PROFILES.Schema)) {
  throw new Error("generated JavaScript ID profile metadata is mutable");
}
if (!Object.isFrozen(AUTHORITY_WIRE_V1) || !Object.isFrozen(AUTHORITY_WIRE_V1.bits)) {
  throw new Error("generated JavaScript authority metadata is mutable");
}
if (!Object.isFrozen(NUMERIC_PROFILES) || !Object.isFrozen(NUMERIC_PROFILES["signed-q32-nearest-ties-even-v1"])) {
  throw new Error("generated JavaScript numeric profile metadata is mutable");
}
for (const value of [1, 128]) {
  let rejected = false;
  try { admitAuthorityWireV1(new Uint8Array([value])); } catch (_) { rejected = true; }
  if (!rejected) throw new Error("generated JavaScript binding admitted authority grant bits");
}
for (const profileId of ["constructor", "toString", "__proto__", "unknown-profile"]) {
  let rejected = false;
  try { numericProfile(profileId); } catch (_) { rejected = true; }
  if (!rejected) throw new Error(`generated JavaScript binding admitted unknown numeric profile: ${profileId}`);
}
for (const variant of ["constructor", "toString", "__proto__", "Unknown"]) {
  let rejected = false;
  try { validateIdProfile("stable-id", variant); } catch (_) { rejected = true; }
  if (!rejected) throw new Error(`generated JavaScript binding admitted unknown ID profile: ${variant}`);
}
const profile = numericProfile("signed-q32-nearest-ties-even-v1");
if (BigInt(profile.scale) !== (1n << 32n)) throw new Error("numeric profile scale drift");
if (profile.rounding !== "nearest-ties-even") throw new Error("numeric profile rounding drift");
if (NUMERIC_PROFILES[profile.id].fixedQ32ArithmeticCompatible !== false) throw new Error("Q32 semantic split lost");
if (FIXED_Q32.arithmeticProfileId !== "fixed-q32-toward-zero-v1") throw new Error("FixedQ32 profile drift");
console.log("platform.types generated JavaScript compatibility: ok");
