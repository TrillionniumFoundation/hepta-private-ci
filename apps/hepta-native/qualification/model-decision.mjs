/** Qualification-only bridge from real typed model probabilities to one bounded
 * clipboard action. This does not select a model, authorize a native capability,
 * or certify calibration. The existing native owner still validates and executes.
 */
import { types } from "node:util";

const ID = /^[A-Za-z0-9._:-]{1,128}$/;
const SHA = /^(?!0{64}$)[0-9a-f]{64}$/;
const SIZES = { action: 6, target: 4, disposition: 6, postcondition: 6, ood: 2 };

function exact(value, fields) {
  if (value === null || typeof value !== "object" || types.isProxy(value) || Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    throw new TypeError("probe decision requires plain own data properties");
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (keys.length !== fields.length || fields.some((key) => !Object.hasOwn(descriptors, key))) {
    throw new TypeError("unknown or missing probe decision field");
  }
  const snapshot = Object.create(null);
  for (const key of keys) {
    const field = descriptors[key];
    if (typeof key !== "string" || !Object.hasOwn(field, "value") || !field.enumerable) {
      throw new TypeError("probe decision requires own data properties");
    }
    snapshot[key] = field.value;
  }
  return Object.freeze(snapshot);
}

function denseArray(value, count, name) {
  if (types.isProxy(value) || !Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype) {
    throw new TypeError(`invalid ${name} array`);
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (descriptors.length.value !== count || Reflect.ownKeys(descriptors).length !== count + 1) {
    throw new TypeError(`invalid ${name} array shape`);
  }
  const snapshot = [];
  for (let index = 0; index < count; index++) {
    const field = descriptors[String(index)];
    if (!field || !Object.hasOwn(field, "value") || !field.enumerable) {
      throw new TypeError(`invalid ${name} array data`);
    }
    snapshot.push(field.value);
  }
  return Object.freeze(snapshot);
}

function distribution(values) {
  if (values.some((value) => typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) ||
      Math.abs(values.reduce((a, b) => a + b, 0) - 1) > 1e-5) {
    throw new TypeError("invalid bounded model probability distribution");
  }
  // Lowest index wins an exact tie, matching the diagnostic head argmax.
  return values.reduce((best, value, index) => value > values[best] ? index : best, 0);
}

export function clipboardChoiceFromModel(value, currentGeneration) {
  value = exact(value, ["schema", "requestId", "replySha256", "projectionSha256", "headManifestSha256",
    "baseSnapshotDigest", "modelSupported", "probabilities", "targets"]);
  if (value.schema !== "hepta.model-native-probe-input.v2" || typeof value.requestId !== "string" ||
      value.requestId.length > 120 || !ID.test(value.requestId) ||
      !Number.isSafeInteger(currentGeneration) || currentGeneration < 1) {
    throw new TypeError("invalid probe identity");
  }
  for (const key of ["replySha256", "projectionSha256", "headManifestSha256", "baseSnapshotDigest"]) {
    if (typeof value[key] !== "string" || !SHA.test(value[key])) throw new TypeError("invalid model binding digest");
  }
  if (typeof value.modelSupported !== "boolean") throw new TypeError("invalid model support decision");
  const raw = exact(value.probabilities, Object.keys(SIZES));
  const probabilities = {}, predicted = {};
  for (const [key, size] of Object.entries(SIZES)) {
    probabilities[key] = denseArray(raw[key], size, "probability");
    predicted[key] = distribution(probabilities[key]);
  }
  const targets = denseArray(value.targets, 4, "target")
    .map((target) => exact(target, ["referenceId", "generation", "text"]));
  const ids = new Set();
  for (const target of targets) {
    if (typeof target.referenceId !== "string" || !ID.test(target.referenceId) || ids.has(target.referenceId) ||
        target.generation !== currentGeneration || typeof target.text !== "string" ||
        !target.text || target.text.includes("\0") || Buffer.byteLength(target.text) > 4096) {
      throw new TypeError("invalid, duplicate or stale frozen target");
    }
    ids.add(target.referenceId);
  }
  // Model abstention is a mandatory veto. The diagnostic thresholds can only
  // narrow its support; neither a true flag nor these thresholds grant authority.
  const confidence = Math.min(...["action", "target", "disposition", "postcondition"]
    .map((key) => probabilities[key][predicted[key]]));
  const ood = probabilities.ood[1];
  if (!value.modelSupported || predicted.action !== 2 || predicted.disposition !== 0 || predicted.postcondition !== 2 ||
      confidence < 0.95 || ood > 0.05) {
    return Object.freeze({ status: "abstained", requestId: value.requestId, replySha256: value.replySha256, predicted: Object.freeze(predicted), confidence, ood, modelSupported: value.modelSupported, authorityGranted: false });
  }
  const target = targets[predicted.target];
  return Object.freeze({ status: "selected", requestId: value.requestId,
    referenceId: target.referenceId, text: target.text, targetIndex: predicted.target,
    confidence, ood, replySha256: value.replySha256, modelSupported: value.modelSupported, authorityGranted: false });
}
