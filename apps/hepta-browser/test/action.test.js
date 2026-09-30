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

test("credential upload and download remain fail-closed future capabilities", () => {
  for (const action of [
    {
      kind: "credential",
      selector: "#password",
      credentialRef: "credential.login.1",
    },
    {
      kind: "upload",
      selector: "input[type=file]",
      fileRef: "artifact.upload.1",
      fileDigest: D1,
      maxBytes: 1024,
    },
    {
      kind: "download",
      url: "https://example.com/file",
      maxBytes: 1024,
    },
  ]) {
    assert.throws(
      () => normalizeBrowserAction(action),
      /future capability and is not connected/,
    );
  }
});
