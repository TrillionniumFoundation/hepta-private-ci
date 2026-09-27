import assert from "node:assert/strict";
import test from "node:test";

import {
  RedactingObservationBrowserDriver,
  redactObservationText,
  redactObservationUrl,
  redactSemanticObservation,
} from "../src/observation-redactor.js";
import { canonicalDigest } from "../src/runtime-contract.js";

const D1 = "1".repeat(64);
const JWT = [
  `eyJ${"a".repeat(16)}`,
  `eyJ${"b".repeat(16)}`,
  "c".repeat(32),
].join(".");
const TOKEN = `EXAMPLE_${"xY9_".repeat(14)}`;

function semanticObservation() {
  return {
    schema: "hepta.browser.semantic-observation.v1",
    title: `Account token=${TOKEN}`,
    visibleText: `Authorization: Bearer ${TOKEN}\nJWT ${JWT}`,
    links: [
      {
        text: `continue ${TOKEN}`,
        href: `https://example.com/path/${TOKEN}?token=${TOKEN}&page=1#${TOKEN}`,
        selector: "html:nth-of-type(1)>body:nth-of-type(1)>a:nth-of-type(1)",
      },
    ],
    controls: [
      {
        selector:
          "html:nth-of-type(1)>body:nth-of-type(1)>input:nth-of-type(1)",
        tag: "input",
        role: "textbox",
        type: "text",
        name: `api_key=${TOKEN}`,
        ariaLabel: `secret=${TOKEN}`,
        placeholder: `Bearer ${TOKEN}`,
        disabled: false,
        checked: false,
      },
    ],
    forms: [
      {
        method: "post",
        action: `https://example.com/submit?session=${TOKEN}#${TOKEN}`,
        controlCount: 1,
        selector: "html:nth-of-type(1)>body:nth-of-type(1)>form:nth-of-type(1)",
      },
    ],
    viewport: { width: 1280, height: 720 },
    truncated: false,
  };
}

test("text and URL redaction removes common secrets deterministically", () => {
  const text = redactObservationText(
    `password=${TOKEN} Authorization: Bearer ${TOKEN} ${JWT}`,
  );
  assert.equal(text.includes(TOKEN), false);
  assert.equal(text.includes(JWT), false);
  assert.match(text, /\[REDACTED\]/);

  const url = redactObservationUrl(
    `https://example.com/path/${TOKEN}?token=${TOKEN}&page=1#${TOKEN}`,
  );
  assert.equal(url.includes(TOKEN), false);
  assert.equal(url.includes("#"), false);
  assert.match(url, /REDACTED/);
});

test("semantic redaction preserves stable action handles and page structure", () => {
  const original = semanticObservation();
  const redacted = redactSemanticObservation(original);
  const serialized = JSON.stringify(redacted);
  assert.equal(serialized.includes(TOKEN), false);
  assert.equal(serialized.includes(JWT), false);
  assert.equal(redacted.schema, original.schema);
  assert.equal(redacted.links[0].selector, original.links[0].selector);
  assert.equal(redacted.controls[0].selector, original.controls[0].selector);
  assert.equal(redacted.forms[0].selector, original.forms[0].selector);
  assert.deepEqual(redacted.viewport, original.viewport);
  assert.equal(redacted.truncated, false);
  assert.equal(Object.isFrozen(redacted), true);
});

test("driver redacts only the upper-layer projection and rebinds its digest", async () => {
  const original = semanticObservation();
  const inner = {
    supportsAbort: true,
    maxActiveProfiles: 4,
    maxOutstandingOperations: 1,
    async start() {
      return { started: true };
    },
    async observe() {
      return {
        pageGeneration: 7,
        origin: "https://example.com",
        documentDigest: D1,
        semanticDigest: canonicalDigest(original),
        semanticObservation: original,
      };
    },
    async dispatch() {
      return { terminalObserved: false };
    },
    async reconcile() {
      return { terminalObserved: false };
    },
    async reconcilePersisted() {
      return { terminalObserved: false };
    },
    async contain() {
      return { contained: true };
    },
    async stop() {
      return { stopped: true };
    },
  };
  const driver = new RedactingObservationBrowserDriver({ driver: inner });
  const observed = await driver.observe({ profileId: "profile.1" });
  assert.equal(observed.documentDigest, D1);
  assert.equal(observed.pageGeneration, 7);
  assert.equal(JSON.stringify(observed.semanticObservation).includes(TOKEN), false);
  assert.equal(
    observed.semanticDigest,
    canonicalDigest(observed.semanticObservation),
  );
  assert.notEqual(observed.semanticDigest, canonicalDigest(original));
});
