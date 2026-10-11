import assert from "node:assert/strict";
import test from "node:test";

import {
  buildNavigationIntent,
  buildLocalNavigationProposalFromCanonicalJson,
  projectPageState,
  projectPageStateFromLocalCanonicalJson,
} from "../src/browser.js";

const digest = "ab".repeat(32);
const navigationSchema =
  "hepta.browser.local-navigation-proposal-input.v1";
const pageSchema = "hepta.browser.local-page-observation.v1";

function canonicalJson(value) {
  const entries = Object.entries(value).sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  return JSON.stringify(Object.fromEntries(entries));
}

test("navigation intent is normalized and authority free", () => {
  const intent = buildNavigationIntent({
    navigationId: "navigation:1",
    tabId: "tab:1",
    url: "https://user:password@example.test/path#fragment",
    policyDigest: digest,
    expectedRevision: 7,
  });
  assert.equal(intent.url, "https://example.test/path");
  assert.equal(intent.networkAuthority, false);
  assert.equal(intent.effectAuthority, false);
  assert.equal(intent.directStoreWrite, false);
});

test("non-web schemes fail closed", () => {
  assert.throws(
    () =>
      buildNavigationIntent({
        navigationId: "navigation:1",
        tabId: "tab:1",
        url: "file:///etc/passwd",
        policyDigest: digest,
        expectedRevision: 7,
      }),
    /HTTP or HTTPS/,
  );
});

test("page projection excludes untrusted payloads", () => {
  const state = projectPageState({
    tabId: "tab:1",
    state: "ready",
    documentDigest: digest,
    sourceRevision: 2,
    documentHtml: "<script>unsafe()</script>",
  });
  assert.deepEqual(state, {
    tabId: "tab:1",
    state: "ready",
    documentDigest: digest,
    sourceRevision: 2,
    interactive: true,
    networkAuthority: false,
    effectAuthority: false,
  });
  assert.equal("documentHtml" in state, false);
});

function navigationInput(url = "https://example.test/path") {
  return {
    schema: navigationSchema,
    navigationId: "navigation:1",
    tabId: "tab:1",
    url,
    policyDigest: digest,
    expectedRevision: 7,
  };
}

test("legacy V1 navigation normalization remains unchanged", () => {
  const intent = buildNavigationIntent(
    navigationInput("https://user:password@example.test/path#fragment"),
  );
  assert.equal(intent.kind, "BrowserNavigationIntentV1");
  assert.equal(intent.url, "https://example.test/path");
});

test("canonical navigation produces an unregistered authority-free proposal", () => {
  const proposal = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(
      navigationInput("https://EXAMPLE.test:443/a/../b#fragment"),
    ),
  );
  assert.deepEqual(proposal, {
    localSchema: "hepta.browser.local-navigation-proposal.v1",
    navigationId: "navigation:1",
    tabId: "tab:1",
    url: "https://example.test/b#fragment",
    policyDigest: digest,
    expectedRevision: 7,
    networkAuthority: false,
    effectAuthority: false,
    directStoreWrite: false,
  });
  assert.equal("kind" in proposal, false);
  assert.equal(Object.isFrozen(proposal), true);
});

test("normalized URL is bounded by final UTF-8 bytes", () => {
  const prefix = "https://example.test/";
  const exact = `${prefix}${"a".repeat(4096 - Buffer.byteLength(prefix))}`;
  const proposal = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(navigationInput(exact)),
  );
  assert.equal(Buffer.byteLength(proposal.url), 4096);

  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson(navigationInput(`${exact}a`)),
      ),
    /UTF-8 byte limit/,
  );
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson(
          navigationInput(`https://example.test/${"é".repeat(1000)}`),
        ),
      ),
    /UTF-8 byte limit/,
  );
});

test("credentials, controls, non-web schemes, and coercion fail closed", () => {
  for (const url of [
    "https://user:password@example.test/path",
    "https://example.test/\npath",
    "file:///etc/passwd",
  ]) {
    assert.throws(
      () =>
        buildLocalNavigationProposalFromCanonicalJson(
          canonicalJson(navigationInput(url)),
        ),
    );
  }

  let coercions = 0;
  const url = {
    toString() {
      coercions += 1;
      return "https://example.test";
    },
  };
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson(navigationInput(url)),
      ),
    /bounded string/,
  );
  assert.equal(coercions, 0);
});

test("canonical page observation rejects unknown fields and zero digest", () => {
  const input = {
    schema: pageSchema,
    tabId: "tab:1",
    state: "ready",
    documentDigest: digest,
    sourceRevision: 2,
  };
  const state = projectPageStateFromLocalCanonicalJson(canonicalJson(input));
  assert.equal(state.interactive, true);
  assert.equal(Object.isFrozen(state), true);

  assert.throws(
    () =>
      projectPageStateFromLocalCanonicalJson(
        canonicalJson({ ...input, documentHtml: "<script>unsafe()</script>" }),
      ),
    /missing, unknown, or unordered fields/,
  );
  assert.throws(
    () =>
      projectPageStateFromLocalCanonicalJson(
        canonicalJson({ ...input, documentDigest: "0".repeat(64) }),
      ),
    /non-zero/,
  );
});

test("canonical JSON rejects duplicates, field reordering, and non-strings", () => {
  const encoded = canonicalJson(navigationInput());
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        encoded.replace(
          '"tabId":"tab:1"',
          '"tabId":"tab:other","tabId":"tab:1"',
        ),
      ),
    /canonical JSON form/,
  );
  const reordered = JSON.stringify({
    schema: navigationSchema,
    tabId: "tab:1",
    navigationId: "navigation:1",
    url: "https://example.test/path",
    policyDigest: digest,
    expectedRevision: 7,
  });
  assert.throws(
    () => buildLocalNavigationProposalFromCanonicalJson(reordered),
    /missing, unknown, or unordered fields/,
  );
  assert.throws(
    () => buildLocalNavigationProposalFromCanonicalJson(new Proxy({}, {})),
    /bounded canonical JSON/,
  );
});

test("local schemas, policy digest, enums, and revisions fail closed", () => {
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson({
          ...navigationInput(),
          schema: "hepta.browser.local-navigation-proposal-input.v2",
        }),
      ),
    /schema is unsupported/,
  );
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson({ ...navigationInput(), policyDigest: "0".repeat(64) }),
      ),
    /must be non-zero/,
  );
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson({ ...navigationInput(), expectedRevision: 0 }),
      ),
    /positive safe integer/,
  );
  const page = {
    schema: pageSchema,
    tabId: "tab:1",
    state: "invented",
    documentDigest: digest,
    sourceRevision: 1,
  };
  assert.throws(
    () => projectPageStateFromLocalCanonicalJson(canonicalJson(page)),
    /state is not registered/,
  );
  assert.throws(
    () =>
      projectPageStateFromLocalCanonicalJson(
        canonicalJson({ ...page, state: "ready", sourceRevision: 0 }),
      ),
    /positive safe integer/,
  );
});

test("both local entrypoints enforce complete closed canonical fields", () => {
  const page = {
    schema: pageSchema,
    tabId: "tab:1",
    state: "ready",
    documentDigest: digest,
    sourceRevision: 1,
  };
  for (const [call, value, missing] of [
    [buildLocalNavigationProposalFromCanonicalJson, navigationInput(), "url"],
    [projectPageStateFromLocalCanonicalJson, page, "state"],
  ]) {
    const absent = { ...value };
    delete absent[missing];
    assert.throws(() => call(canonicalJson(absent)), /missing, unknown/);
    assert.throws(
      () => call(canonicalJson({ ...value, unknown: true })),
      /missing, unknown/,
    );
    assert.throws(
      () => call(`${canonicalJson(value)}\n`),
      /canonical JSON form/,
    );
    assert.throws(
      () => call(canonicalJson(value).replace('"schema"', '"\\u0073chema"')),
      /canonical JSON form/,
    );
  }
});

test("local entrypoints reject hostile objects without invoking traps", () => {
  for (const call of [
    buildLocalNavigationProposalFromCanonicalJson,
    projectPageStateFromLocalCanonicalJson,
  ]) {
    let traps = 0;
    const hostile = new Proxy(
      {},
      {
        get() {
          traps += 1;
          throw new Error("unexpected get");
        },
        ownKeys() {
          traps += 1;
          throw new Error("unexpected ownKeys");
        },
      },
    );
    assert.throws(() => call(hostile), /bounded canonical JSON/);
    assert.equal(traps, 0);

    let toJsonReads = 0;
    const hostileToJson = {};
    Object.defineProperty(hostileToJson, "toJSON", {
      get() {
        toJsonReads += 1;
        throw new Error("unexpected toJSON read");
      },
    });
    assert.throws(() => call(hostileToJson), /bounded canonical JSON/);
    assert.equal(toJsonReads, 0);
  }
});

test("local JSON input byte ceiling is inclusive at 8192", () => {
  const exactBytes = `"${"é".repeat(4095)}"`;
  assert.equal(Buffer.byteLength(exactBytes), 8192);
  assert.throws(
    () => buildLocalNavigationProposalFromCanonicalJson(exactBytes),
    /must be an object/,
  );
  assert.throws(
    () => buildLocalNavigationProposalFromCanonicalJson(`${exactBytes}a`),
    /canonical JSON byte limit/,
  );
  assert.throws(
    () => buildLocalNavigationProposalFromCanonicalJson(" ".repeat(8193)),
    /bounded canonical JSON/,
  );
});

test("WHATWG normalization has exact Unicode and IDNA boundaries", () => {
  const normalizedPrefix = "https://xn--bcher-kva.example/";
  const remaining = 4096 - Buffer.byteLength(normalizedPrefix);
  const unicodeCount = Math.floor(remaining / 6);
  const asciiCount = remaining % 6;
  const exactUrl = `https://bücher.example/${"a".repeat(asciiCount)}${"é".repeat(unicodeCount)}`;
  const exact = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(navigationInput(exactUrl)),
  );
  assert.equal(Buffer.byteLength(exact.url), 4096);
  assert.equal(exact.url.startsWith(normalizedPrefix), true);
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson(navigationInput(`${exactUrl}é`)),
      ),
    /UTF-8 byte limit/,
  );

  const normalized = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(
      navigationInput("https://BÜCHER.example:443/a/../b#fragment"),
    ),
  );
  assert.equal(normalized.url, "https://xn--bcher-kva.example/b#fragment");
});

test("lone UTF-16 surrogates are rejected without rejecting replacement characters", () => {
  for (const suffix of ["\ud800", "\udfff", "\ud800A", "A\udfff"]) {
    assert.throws(
      () =>
        buildLocalNavigationProposalFromCanonicalJson(
          canonicalJson(navigationInput(`https://example.test/${suffix}`)),
        ),
      /well-formed Unicode/,
    );
  }

  const replacement = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(navigationInput("https://example.test/\ufffd")),
  );
  assert.equal(replacement.url, "https://example.test/%EF%BF%BD");

  const scalarPair = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(navigationInput("https://example.test/😀")),
  );
  assert.equal(scalarPair.url, "https://example.test/%F0%9F%98%80");
});

test("encoded controls and all empty userinfo slash forms are rejected", () => {
  for (const url of [
    "https://example.test/%0aheader",
    "https://example.test/%7Ftail",
    "https://@example.test/path",
    "https:@example.test/path",
    "https:/@example.test/path",
    "https:/:@example.test/path",
    "https:////@example.test/path",
    "https:///\\@example.test/path",
    "HTTPS:/@example.test/path",
  ]) {
    assert.throws(
      () =>
        buildLocalNavigationProposalFromCanonicalJson(
          canonicalJson(navigationInput(url)),
        ),
    );
  }
});

test("at signs in path and query are not mistaken for userinfo", () => {
  const proposal = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(
      navigationInput(
        "https://example.test/@name?email=user@example.test#@fragment",
      ),
    ),
  );
  assert.equal(
    proposal.url,
    "https://example.test/@name?email=user@example.test#@fragment",
  );

  const backslashPath = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(navigationInput("https://example.test\\@name/path")),
  );
  assert.equal(backslashPath.url, "https://example.test/@name/path");
});

test("port lower, upper, and overflow boundaries are deterministic", () => {
  for (const port of [0, 65535]) {
    const proposal = buildLocalNavigationProposalFromCanonicalJson(
      canonicalJson(navigationInput(`https://example.test:${port}/path`)),
    );
    assert.equal(proposal.url, `https://example.test:${port}/path`);
  }
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson(navigationInput("https://example.test:65536/path")),
      ),
    /absolute URL/,
  );
});

test("WHATWG path normalization handles encoded dots and backslashes", () => {
  const encodedDot = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(navigationInput("https://example.test/a/%2e%2e/b")),
  );
  assert.equal(encodedDot.url, "https://example.test/b");

  const backslash = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson(navigationInput("https://example.test/a\\b")),
  );
  assert.equal(backslash.url, "https://example.test/a/b");
});

test("stable identifier and maximum revision boundaries are exact", () => {
  const exact = buildLocalNavigationProposalFromCanonicalJson(
    canonicalJson({
      ...navigationInput(),
      navigationId: "x".repeat(128),
      expectedRevision: Number.MAX_SAFE_INTEGER,
    }),
  );
  assert.equal(exact.navigationId.length, 128);
  assert.equal(exact.expectedRevision, Number.MAX_SAFE_INTEGER);
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson({ ...navigationInput(), navigationId: "x".repeat(129) }),
      ),
    /bounded stable identifier/,
  );
  assert.throws(
    () =>
      buildLocalNavigationProposalFromCanonicalJson(
        canonicalJson({
          ...navigationInput(),
          expectedRevision: Number.MAX_SAFE_INTEGER + 1,
        }),
      ),
    /positive safe integer/,
  );
});
