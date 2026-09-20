// Consumer compatibility gate for generated Platform Types JavaScript binding.
import {
  STABLE_ID_MAX_BYTES,
  FIXED_Q32,
  NUMERIC_PROFILES,
  admitAuthorityWireV1,
  numericProfile,
  validateIdProfile,
} from "../generated/javascript/hepta_platform_types_v1.mjs";

if (STABLE_ID_MAX_BYTES !== 128) throw new Error("stable ID bound drift");
validateIdProfile("schema:numeric-signal", "Schema");
validateIdProfile("normalization:identity", "Normalization");
admitAuthorityWireV1(new Uint8Array([0]));
for (const value of [1, 128]) {
  let rejected = false;
  try { admitAuthorityWireV1(new Uint8Array([value])); } catch (_) { rejected = true; }
  if (!rejected) throw new Error("generated JavaScript binding admitted authority grant bits");
}
const profile = numericProfile("signed-q32-nearest-ties-even-v1");
if (BigInt(profile.scale) !== (1n << 32n)) throw new Error("numeric profile scale drift");
if (profile.rounding !== "nearest-ties-even") throw new Error("numeric profile rounding drift");
if (NUMERIC_PROFILES[profile.id].fixedQ32ArithmeticCompatible !== false) throw new Error("Q32 semantic split lost");
if (FIXED_Q32.arithmeticProfileId !== "fixed-q32-toward-zero-v1") throw new Error("FixedQ32 profile drift");
console.log("platform.types generated JavaScript compatibility: ok");
