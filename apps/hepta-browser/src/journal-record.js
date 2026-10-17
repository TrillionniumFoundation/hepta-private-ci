function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

const MUTABLE_FIELDS = new Set([
  "status",
  "outcomeDigest",
  "terminalObserved",
  "observationReason",
]);
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;

function freezeScalarRecord(record) {
  requireRecord(record, "journal record");
  const snapshot = { ...record };
  for (const value of Object.values(snapshot)) {
    if (
      value !== null &&
      typeof value !== "string" &&
      typeof value !== "boolean" &&
      !(typeof value === "number" && Number.isSafeInteger(value))
    ) {
      throw new TypeError("journal record fields must be JSON scalars");
    }
  }
  for (const field of ["profileId", "operationId"]) {
    if (
      typeof snapshot[field] !== "string" ||
      !STABLE_ID.test(snapshot[field])
    ) {
      throw new TypeError(
        `journal ${field} must be a bounded stable identifier`,
      );
    }
  }
  if (!Number.isSafeInteger(snapshot.generation) || snapshot.generation < 1) {
    throw new TypeError("journal generation must be a positive safe integer");
  }
  for (const field of ["requestDigest", "semanticDigest"]) {
    if (
      typeof snapshot[field] !== "string" ||
      !DIGEST.test(snapshot[field]) ||
      snapshot[field] === "0".repeat(64)
    ) {
      throw new TypeError(
        `journal ${field} must be a non-zero lowercase SHA-256 digest`,
      );
    }
  }
  if (snapshot.terminalObserved === true) {
    if (
      (snapshot.status !== "succeeded" && snapshot.status !== "failed") ||
      typeof snapshot.outcomeDigest !== "string" ||
      !DIGEST.test(snapshot.outcomeDigest) ||
      snapshot.outcomeDigest === "0".repeat(64)
    ) {
      throw new TypeError("journal terminal result is invalid");
    }
  } else if (
    snapshot.terminalObserved !== false ||
    snapshot.status !== "indeterminate" ||
    snapshot.outcomeDigest !== null
  ) {
    throw new TypeError("journal indeterminate result is invalid");
  }
  return Object.freeze(snapshot);
}

// Primary V1 persisted reconciliation spread a receipt over the durable record.
// These exact four fields carried no authority. Keep them in replayed records;
// only their validated comparison view is excluded from operation semantics.
const LEGACY_RECEIPT_FIELDS = new Map([
  ["kind", "BrowserEffectObservationV1"],
  ["networkAuthority", false],
  ["filesystemAuthority", false],
  ["credentialExportAuthority", false],
]);
const LEGACY_RECEIPT_KEYS = new Set(LEGACY_RECEIPT_FIELDS.keys());
const IMMUTABLE_EXCLUSIONS = new Set([
  ...MUTABLE_FIELDS,
  ...LEGACY_RECEIPT_KEYS,
]);

function hasReceiptMetadata(record) {
  return [...LEGACY_RECEIPT_KEYS].some((key) => Object.hasOwn(record, key));
}

export function freezeRecord(record) {
  const snapshot = freezeScalarRecord(record);
  if (hasReceiptMetadata(snapshot)) {
    throw new TypeError(
      "receipt metadata is admitted only from checksummed V1 history",
    );
  }
  return snapshot;
}

// Call only after the raw V1 envelope checksum and type have been validated.
export function freezeReplayRecord(record, type) {
  const snapshot = freezeScalarRecord(record);
  if (hasReceiptMetadata(snapshot)) {
    if (
      type !== "observation" ||
      ![...LEGACY_RECEIPT_FIELDS].every(
        ([key, value]) =>
          Object.hasOwn(snapshot, key) && snapshot[key] === value,
      )
    ) {
      throw new TypeError("historical V1 receipt metadata is invalid");
    }
  }
  return snapshot;
}

function sameFields(left, right, excluded = new Set()) {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].every(
    (key) =>
      excluded.has(key) ||
      (Object.hasOwn(left, key) === Object.hasOwn(right, key) &&
        left[key] === right[key]),
  );
}

export function applyRecord(prior, record, type) {
  if (prior && !sameFields(prior, record, IMMUTABLE_EXCLUSIONS)) {
    throw new TypeError("journal operation changed immutable semantics");
  }
  if (type === "dispatch") {
    if (record.terminalObserved)
      throw new TypeError("journal dispatch must be indeterminate");
    // A repeated intent cannot erase progress already observed for that intent.
    return prior ?? record;
  }
  if (!prior) throw new TypeError("journal observation has no dispatch intent");
  if (
    prior.terminalObserved &&
    !sameFields(prior, record, LEGACY_RECEIPT_KEYS)
  ) {
    throw new TypeError(
      "journal terminal result cannot be changed or rolled back",
    );
  }
  // Preserve historical receipt adornments even when a later canonical line
  // omits them. Raw lines/checksums are never rewritten or normalized.
  const merged = Object.freeze({ ...prior, ...record });
  return sameFields(prior, merged) ? prior : merged;
}

export function keyOf(record) {
  return `${record.profileId}\u0000${record.generation}\u0000${record.operationId}`;
}
