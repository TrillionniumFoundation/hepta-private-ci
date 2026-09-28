import {
  computerActionAuthorityBindingDigestV1,
  decodeComputerActionFrameV1,
} from "../../../codex-rs/hepta-wire/js/computer-action-ir.js";
import {
  browserActionDestinationOrigin,
  browserActionDigest,
  normalizeBrowserAction,
} from "./action.js";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);

function record(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function exactKeys(value, expected, name) {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((key, index) => key !== wanted[index])) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positive(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

async function resolve(resolver, request, expectedKeys, name) {
  const value = record(await resolver.resolve(request), name);
  exactKeys(value, expectedKeys, name);
  return value;
}

export async function browserOperationFromComputerActionV1({
  frameBytes,
  profileId,
  principalId,
  generation,
  pageGeneration,
  documentDigest,
  currentOrigin,
  effectGrantDigest,
  authorityEpoch,
  admittedMonotonicMicros,
  admittedWallTimeMs,
  actuatorId,
  resolver,
}) {
  record(resolver, "resolver");
  if (typeof resolver.resolve !== "function") {
    throw new TypeError("resolver.resolve must be a function");
  }
  const frame = decodeComputerActionFrameV1(frameBytes);
  const acceptedProfileId = stableId(profileId, "profileId");
  const acceptedPrincipalId = stableId(principalId, "principalId");
  const acceptedGeneration = positive(generation, "generation");
  const acceptedPageGeneration = positive(pageGeneration, "pageGeneration");
  const acceptedMonotonicMicros = positive(
    admittedMonotonicMicros,
    "admittedMonotonicMicros",
  );
  const acceptedWallTimeMs = positive(admittedWallTimeMs, "admittedWallTimeMs");
  let acceptedCurrentOrigin;
  try {
    acceptedCurrentOrigin = new URL(currentOrigin).origin;
  } catch {
    throw new TypeError("currentOrigin must be an absolute URL origin");
  }
  if (acceptedCurrentOrigin !== currentOrigin) {
    throw new TypeError("currentOrigin must be canonical");
  }
  if (frame.actuatorId !== stableId(actuatorId, "actuatorId")) {
    throw new TypeError("binary browser actuator mismatch");
  }
  if (frame.subjectId !== acceptedPrincipalId) {
    throw new TypeError("binary browser subject mismatch");
  }
  if (frame.sessionGeneration !== acceptedGeneration) {
    throw new TypeError("binary browser session generation mismatch");
  }
  if (frame.bodyGeneration !== acceptedPageGeneration) {
    throw new TypeError("binary browser page generation mismatch");
  }
  if (frame.observationRevision !== acceptedPageGeneration) {
    throw new TypeError("binary browser observation revision mismatch");
  }
  if (frame.preconditionDigest !== digest(documentDigest, "documentDigest")) {
    throw new TypeError("binary browser precondition does not bind the current document");
  }

  let typedAction;
  switch (frame.opcode) {
    case "navigate_reference": {
      if (frame.payload.kind !== "reference") {
        throw new TypeError("navigate payload is not a reference");
      }
      const value = await resolve(
        resolver,
        {
          kind: "navigation",
          referenceId: frame.payload.referenceId,
          operationId: frame.operationId,
          subjectId: frame.subjectId,
          observationRevision: frame.observationRevision,
        },
        ["url", "policyDigest", "expectedRevision"],
        "resolved navigation reference",
      );
      typedAction = normalizeBrowserAction({
        kind: "navigate",
        url: value.url,
        policyDigest: value.policyDigest,
        expectedRevision: value.expectedRevision,
      });
      break;
    }
    case "focus_target":
    case "activate_target": {
      const value = await resolve(
        resolver,
        {
          kind: "target",
          targetRef: frame.targetRef,
          operationId: frame.operationId,
          subjectId: frame.subjectId,
          observationRevision: frame.observationRevision,
        },
        ["selector"],
        "resolved browser target",
      );
      typedAction = normalizeBrowserAction({
        kind: frame.opcode === "focus_target" ? "focus" : "click",
        selector: value.selector,
      });
      break;
    }
    case "type_text_reference": {
      if (frame.payload.kind !== "reference") {
        throw new TypeError("type payload is not a reference");
      }
      const target = await resolve(
        resolver,
        {
          kind: "target",
          targetRef: frame.targetRef,
          operationId: frame.operationId,
          subjectId: frame.subjectId,
          observationRevision: frame.observationRevision,
        },
        ["selector"],
        "resolved browser target",
      );
      const text = await resolve(
        resolver,
        {
          kind: "text",
          referenceId: frame.payload.referenceId,
          operationId: frame.operationId,
          subjectId: frame.subjectId,
          observationRevision: frame.observationRevision,
        },
        ["text"],
        "resolved browser text reference",
      );
      typedAction = normalizeBrowserAction({
        kind: "type",
        selector: target.selector,
        text: text.text,
      });
      break;
    }
    case "wait_observation": {
      if (frame.payload.kind !== "wait") {
        throw new TypeError("wait payload is invalid");
      }
      typedAction = normalizeBrowserAction({
        kind: "wait",
        condition: "load-complete",
        timeoutMs: Math.max(1, Math.floor(frame.payload.waitMicros / 1000)),
      });
      break;
    }
    default:
      throw new TypeError("binary action is not supported by browser.servo");
  }

  const finalPayloadDigest = browserActionDigest(typedAction);
  if (finalPayloadDigest !== frame.finalPayloadDigest) {
    throw new TypeError("resolved browser action does not match finalPayloadDigest");
  }
  const actionOrigin = browserActionDestinationOrigin(typedAction);
  const destinationOrigin = actionOrigin ?? acceptedCurrentOrigin;
  if (frame.deadlineMonotonicMicros <= acceptedMonotonicMicros) {
    throw new TypeError("binary browser deadline has expired");
  }
  const remainingMicros = frame.deadlineMonotonicMicros - acceptedMonotonicMicros;
  const remainingMs = Math.max(1, Math.ceil(remainingMicros / 1000));
  const deadlineMs = acceptedWallTimeMs + remainingMs;
  if (!Number.isSafeInteger(deadlineMs) || deadlineMs <= acceptedWallTimeMs) {
    throw new TypeError("binary browser deadline is outside the safe range");
  }
  return Object.freeze({
    profileId: acceptedProfileId,
    principalId: acceptedPrincipalId,
    generation: acceptedGeneration,
    operationId: frame.operationId,
    pageGeneration: acceptedPageGeneration,
    typedAction,
    destinationOrigin,
    finalPayloadDigest,
    sourceActionDigest: computerActionAuthorityBindingDigestV1(frame),
    effectGrantDigest: digest(effectGrantDigest, "effectGrantDigest"),
    authorityEpoch: positive(authorityEpoch, "authorityEpoch"),
    deadlineMs,
  });
}
