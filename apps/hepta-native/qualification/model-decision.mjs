/** Qualification-only bridge from real typed model probabilities to one bounded
 * clipboard action. This does not select a model, authorize a native capability,
 * or certify calibration. The existing native owner still validates and executes.
 */
const ID = /^[A-Za-z0-9._:-]{1,128}$/;
const SHA = /^(?!0{64}$)[0-9a-f]{64}$/;
const SIZES = { action: 6, target: 4, disposition: 6, postcondition: 6, ood: 2 };

function exact(value, fields) {
  if (value === null || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== fields.length || fields.some((key) => !Object.hasOwn(value, key))) {
    throw new TypeError("unknown or missing probe decision field");
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Reflect.ownKeys(descriptors).some((key) => typeof key !== "string" ||
      !Object.hasOwn(descriptors[key], "value") || !descriptors[key].enumerable)) {
    throw new TypeError("probe decision requires own data properties");
  }
}

function distribution(values, count) {
  if (!Array.isArray(values) || values.length !== count ||
      Array.from({ length: count }, (_, i) => Object.getOwnPropertyDescriptor(values, String(i)))
        .some((field) => !field || !Object.hasOwn(field, "value")) ||
      values.some((value) => typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) ||
      Math.abs(values.reduce((a, b) => a + b, 0) - 1) > 1e-5) {
    throw new TypeError("invalid bounded model probability distribution");
  }
  // Lowest index wins an exact tie, matching the diagnostic head argmax.
  return values.reduce((best, value, index) => value > values[best] ? index : best, 0);
}

export function clipboardChoiceFromModel(value, currentGeneration) {
  exact(value, ["schema", "requestId", "replySha256", "projectionSha256", "headManifestSha256",
    "baseSnapshotDigest", "probabilities", "targets"]);
  if (value.schema !== "hepta.model-native-probe-input.v1" || typeof value.requestId !== "string" ||
      value.requestId.length > 120 || !ID.test(value.requestId) ||
      !Number.isSafeInteger(currentGeneration) || currentGeneration < 1) {
    throw new TypeError("invalid probe identity");
  }
  for (const key of ["replySha256", "projectionSha256", "headManifestSha256", "baseSnapshotDigest"]) {
    if (typeof value[key] !== "string" || !SHA.test(value[key])) throw new TypeError("invalid model binding digest");
  }
  exact(value.probabilities, Object.keys(SIZES));
  const predicted = {};
  for (const [key, size] of Object.entries(SIZES)) predicted[key] = distribution(value.probabilities[key], size);
  if (!Array.isArray(value.targets) || value.targets.length !== 4) throw new TypeError("four frozen targets required");
  const ids = new Set();
  for (const target of value.targets) {
    exact(target, ["referenceId", "generation", "text"]);
    if (typeof target.referenceId !== "string" || !ID.test(target.referenceId) || ids.has(target.referenceId) ||
        target.generation !== currentGeneration || typeof target.text !== "string" ||
        !target.text || target.text.includes("\0") || Buffer.byteLength(target.text) > 4096) {
      throw new TypeError("invalid, duplicate or stale frozen target");
    }
    ids.add(target.referenceId);
  }
  // Predeclared diagnostic policy, not production calibration or a learned veto.
  const confidence = Math.min(...["action", "target", "disposition", "postcondition"]
    .map((key) => value.probabilities[key][predicted[key]]));
  const ood = value.probabilities.ood[1];
  if (predicted.action !== 2 || predicted.disposition !== 0 || predicted.postcondition !== 2 ||
      confidence < 0.95 || ood > 0.05) {
    return Object.freeze({ status: "abstained", requestId: value.requestId, replySha256: value.replySha256, predicted: Object.freeze(predicted), confidence, ood, authorityGranted: false });
  }
  const target = value.targets[predicted.target];
  return Object.freeze({ status: "selected", requestId: value.requestId,
    referenceId: target.referenceId, text: target.text, targetIndex: predicted.target,
    confidence, ood, replySha256: value.replySha256, authorityGranted: false });
}
