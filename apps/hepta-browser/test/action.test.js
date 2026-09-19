import assert from "node:assert/strict";
import test from "node:test";

import { browserActionDigest, normalizeBrowserAction } from "../src/action.js";

const D1 = "1".repeat(64);

test("navigation digest binds policy and expected revision", () => {
  const left = browserActionDigest({
    kind: "navigate",
    url: "https://example.com/path",
    policyDigest: D1,
    expectedRevision: 7,
  });
  const right = browserActionDigest({
    kind: "navigate",
    url: "https://example.com/path",
    policyDigest: D1,
    expectedRevision: 8,
  });
  assert.notEqual(left, right);
});

test("credential and upload actions carry references, never ambient secret or path fields", () => {
  assert.deepEqual(
    normalizeBrowserAction({
      kind: "credential",
      selector: "#password",
      credentialRef: "credential.login.1",
    }),
    {
      kind: "credential",
      selector: "#password",
      credentialRef: "credential.login.1",
    },
  );
  assert.throws(
    () =>
      normalizeBrowserAction({
        kind: "credential",
        selector: "#password",
        credentialRef: "credential.login.1",
        secret: "raw-secret",
      }),
    /missing or unknown fields/,
  );
  assert.deepEqual(
    normalizeBrowserAction({
      kind: "upload",
      selector: "input[type=file]",
      fileRef: "artifact.upload.1",
      fileDigest: D1,
      maxBytes: 1024,
    }),
    {
      kind: "upload",
      selector: "input[type=file]",
      fileRef: "artifact.upload.1",
      fileDigest: D1,
      maxBytes: 1024,
    },
  );
  assert.throws(
    () =>
      normalizeBrowserAction({
        kind: "upload",
        selector: "input[type=file]",
        fileRef: "artifact.upload.1",
        fileDigest: D1,
        maxBytes: 1024,
        path: "/private/file",
      }),
    /missing or unknown fields/,
  );
});
