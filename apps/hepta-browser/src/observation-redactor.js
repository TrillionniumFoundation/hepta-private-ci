import { canonicalDigest } from "./runtime-contract.js";

const MAX_TEXT_BYTES = 65_536;
const UTF8 = new TextEncoder();
const REDACTED = "[REDACTED]";
const SECRET_KEY =
  /\b(token|secret|password|passwd|passphrase|api[_-]?key|access[_-]?key|session(?:[_-]?id)?|authorization|credential|signature|sig)\b/i;
const KEY_VALUE_SECRET =
  /\b(token|secret|password|passwd|passphrase|api[_-]?key|access[_-]?key|session(?:[_-]?id)?|authorization|credential|signature|sig)\b\s*[:=]\s*["']?[^\s,;"']{1,512}/gi;
const BEARER = /\bBearer\s+[A-Za-z0-9._~+/=-]{8,512}\b/gi;
const JWT = /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g;
const LONG_HEX = /\b[0-9a-fA-F]{32,}\b/g;
const HIGH_ENTROPY = /\b[A-Za-z0-9_-]{40,}\b/g;

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function boundedString(value, name, maximum = MAX_TEXT_BYTES) {
  if (typeof value !== "string") {
    throw new TypeError(`${name} must be a string`);
  }
  if (UTF8.encode(value).byteLength > maximum) {
    throw new TypeError(`${name} exceeds the redaction byte bound`);
  }
  return value;
}

export function redactObservationText(value) {
  return boundedString(value, "observation text")
    .replace(BEARER, `Bearer ${REDACTED}`)
    .replace(JWT, REDACTED)
    .replace(KEY_VALUE_SECRET, (_match, key) => `${key}=${REDACTED}`)
    .replace(LONG_HEX, REDACTED)
    .replace(HIGH_ENTROPY, REDACTED);
}

function redactPathSegment(segment) {
  if (segment.length >= 24 && (LONG_HEX.test(segment) || HIGH_ENTROPY.test(segment))) {
    LONG_HEX.lastIndex = 0;
    HIGH_ENTROPY.lastIndex = 0;
    return REDACTED;
  }
  LONG_HEX.lastIndex = 0;
  HIGH_ENTROPY.lastIndex = 0;
  return segment;
}

export function redactObservationUrl(value) {
  const raw = boundedString(value, "observation URL", 4096);
  if (raw.length === 0) return raw;
  let url;
  try {
    url = new URL(raw);
  } catch {
    return REDACTED;
  }
  if (!["http:", "https:"].includes(url.protocol)) return REDACTED;
  url.username = "";
  url.password = "";
  for (const key of [...url.searchParams.keys()]) {
    url.searchParams.set(key, REDACTED);
  }
  url.hash = "";
  url.pathname = url.pathname
    .split("/")
    .map((segment) => redactPathSegment(segment))
    .join("/");
  return url.toString();
}

function redactNamedText(value, name, maximum) {
  const text = boundedString(value, name, maximum);
  if (SECRET_KEY.test(name) && text.length > 0) return REDACTED;
  return redactObservationText(text);
}

export function redactSemanticObservation(value) {
  const observation = requireRecord(value, "semanticObservation");
  const links = Array.isArray(observation.links) ? observation.links : [];
  const controls = Array.isArray(observation.controls)
    ? observation.controls
    : [];
  const forms = Array.isArray(observation.forms) ? observation.forms : [];
  const viewport = requireRecord(observation.viewport, "semantic viewport");

  const redacted = {
    schema: boundedString(observation.schema, "semantic schema", 128),
    title: redactObservationText(
      boundedString(observation.title, "semantic title", 1024),
    ),
    visibleText: redactObservationText(
      boundedString(observation.visibleText, "semantic visibleText"),
    ),
    links: links.map((entry, index) => {
      const link = requireRecord(entry, `semantic link ${index}`);
      return {
        text: redactObservationText(
          boundedString(link.text, `semantic link ${index} text`, 512),
        ),
        href: redactObservationUrl(link.href),
        selector: boundedString(
          link.selector,
          `semantic link ${index} selector`,
          2048,
        ),
      };
    }),
    controls: controls.map((entry, index) => {
      const control = requireRecord(entry, `semantic control ${index}`);
      return {
        selector: boundedString(
          control.selector,
          `semantic control ${index} selector`,
          2048,
        ),
        tag: boundedString(control.tag, `semantic control ${index} tag`, 32),
        role: boundedString(control.role, `semantic control ${index} role`, 64),
        type: boundedString(control.type, `semantic control ${index} type`, 64),
        name: redactNamedText(
          control.name,
          `semantic control ${index} name`,
          128,
        ),
        ariaLabel: redactNamedText(
          control.ariaLabel,
          `semantic control ${index} ariaLabel`,
          512,
        ),
        placeholder: redactNamedText(
          control.placeholder,
          `semantic control ${index} placeholder`,
          512,
        ),
        disabled: control.disabled === true,
        checked: control.checked === true,
      };
    }),
    forms: forms.map((entry, index) => {
      const form = requireRecord(entry, `semantic form ${index}`);
      return {
        method: boundedString(
          form.method,
          `semantic form ${index} method`,
          16,
        ),
        action: redactObservationUrl(form.action),
        controlCount:
          Number.isSafeInteger(form.controlCount) && form.controlCount >= 0
            ? form.controlCount
            : 0,
        selector: boundedString(
          form.selector,
          `semantic form ${index} selector`,
          2048,
        ),
      };
    }),
    viewport: {
      width:
        Number.isSafeInteger(viewport.width) && viewport.width >= 0
          ? viewport.width
          : 0,
      height:
        Number.isSafeInteger(viewport.height) && viewport.height >= 0
          ? viewport.height
          : 0,
    },
    truncated: observation.truncated === true,
  };
  return Object.freeze(JSON.parse(JSON.stringify(redacted)));
}

export class RedactingObservationBrowserDriver {
  supportsAbort = true;
  maxActiveProfiles;
  maxOutstandingOperations;
  #driver;

  constructor({ driver }) {
    requireRecord(driver, "redacting observation driver");
    for (const method of [
      "start",
      "observe",
      "dispatch",
      "reconcile",
      "reconcilePersisted",
      "contain",
      "stop",
    ]) {
      if (typeof driver[method] !== "function") {
        throw new TypeError(`redacting observation driver.${method} is required`);
      }
    }
    if (driver.supportsAbort !== true) {
      throw new TypeError("redacting observation driver must support abort");
    }
    this.#driver = driver;
    this.maxActiveProfiles = driver.maxActiveProfiles;
    this.maxOutstandingOperations = driver.maxOutstandingOperations;
  }

  start(input, options = {}) {
    return this.#driver.start(input, options);
  }

  async observe(input, options = {}) {
    const observed = requireRecord(
      await this.#driver.observe(input, options),
      "redacting observation",
    );
    const semanticObservation = redactSemanticObservation(
      observed.semanticObservation,
    );
    return Object.freeze({
      ...observed,
      semanticObservation,
      semanticDigest: canonicalDigest(semanticObservation),
    });
  }

  dispatch(input, options = {}) {
    return this.#driver.dispatch(input, options);
  }

  reconcile(input, options = {}) {
    return this.#driver.reconcile(input, options);
  }

  reconcilePersisted(input, options = {}) {
    return this.#driver.reconcilePersisted(input, options);
  }

  contain(input) {
    return this.#driver.contain(input);
  }

  stop(input, options = {}) {
    return this.#driver.stop(input, options);
  }
}
