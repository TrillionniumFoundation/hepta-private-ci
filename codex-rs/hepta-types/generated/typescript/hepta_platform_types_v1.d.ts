// GENERATED from bindings/PLATFORM_TYPES_BINDINGS_V1.json; DO NOT EDIT.
export type IdProfileV1 = "Stable" | "Module" | "Namespaced" | "Execution" | "Schema" | "Normalization" | "Receipt" | "Artifact";
export type NumericProfileIdV1 = "hnmf-ppm-toward-zero-v1" | "signed-q24-nearest-ties-even-v1" | "signed-q32-nearest-ties-even-v1";
export interface NumericProfileDefinitionV1 {
  readonly id: NumericProfileIdV1;
  readonly version: number;
  readonly scale: string;
  readonly rounding: "toward-zero" | "nearest-ties-even";
  readonly sharesFixedQ32RawScale?: boolean;
  readonly fixedQ32ArithmeticCompatible?: boolean;
}
export declare const STABLE_ID_MAX_BYTES: number;
export declare const ID_PROFILES: Readonly<Record<IdProfileV1, Readonly<{id: string; prefix?: string}>>>;
export declare const AUTHORITY_WIRE_V1: Readonly<{encodedBytes: number; trustedMask: number; bits: Readonly<Record<string, number>>}>;
export declare const FIXED_Q32: Readonly<{scale: string; arithmeticProfileId: string; multiplyDivideRounding: string}>;
export declare const NUMERIC_PROFILES: Readonly<Record<NumericProfileIdV1, NumericProfileDefinitionV1>>;
export declare const CANONICAL_DIGEST_V1: Readonly<{magic: string; encodingVersion: number; domain: string; maxEncodedBytes: number; maxContainerItems: number; maxDepth: number}>;
export declare function numericProfile(profileId: NumericProfileIdV1): NumericProfileDefinitionV1;
export declare function admitAuthorityWireV1(raw: Uint8Array): void;
export declare function validateIdProfile(value: string, variant: IdProfileV1): string;
