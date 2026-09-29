import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  REQUIRED_REAL_BACKEND_CASES,
} from "../../../qualification/ui-control/external-evidence-repository.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const contract = readFileSync(
  `${root}qualification/ui-control/real-backend-contract.mjs`,
  "utf8",
);
const serverContract = readFileSync(
  `${root}docs/modules/ui.control/SERVER_IDEMPOTENCY.md`,
  "utf8",
);

test("real-backend required cases include cross-principal operation rebind conflict", () => {
  const caseName = "cross-identity-operation-rebind-conflict";
  assert.equal(
    REQUIRED_REAL_BACKEND_CASES.filter(value => value === caseName).length,
    1,
  );
  assert.ok(
    REQUIRED_REAL_BACKEND_CASES.indexOf(caseName) >
      REQUIRED_REAL_BACKEND_CASES.indexOf("cross-identity-lookup-denied"),
  );
  assert.ok(
    REQUIRED_REAL_BACKEND_CASES.indexOf(caseName) <
      REQUIRED_REAL_BACKEND_CASES.indexOf("first-operation-terminal-lookup"),
  );
});

test("real-backend probe rejects same-digest rebind and rechecks the original durable record", () => {
  assert.ok(contract.includes('stage = "cross-identity-operation-rebind"'));
  assert.ok(contract.includes("sessionId: secondary.sessionId"));
  assert.ok(contract.includes("connectionGeneration: secondary.connectionGeneration"));
  assert.ok(contract.includes("crossIdentityRebindBody,\n    secondaryCookie,\n    secondaryCsrf"));
  assert.ok(contract.includes("crossIdentityRebind.response.status === 409"));
  assert.ok(contract.includes("primaryAfterCrossIdentityRebind"));
  assert.ok(contract.includes("expectedAuditTraceId: duplicateAuditTraceId"));
  assert.ok(contract.includes('completedCases.push("cross-identity-operation-rebind-conflict")'));
});

test("server idempotency contract binds replay to authority as well as semantic digest", () => {
  assert.match(
    serverContract,
    /same semantic digest under another session or principal/u,
  );
  assert.match(
    serverContract,
    /second authenticated identity cannot rebind the same operation ID/u,
  );
  assert.match(
    serverContract,
    /rejected attempt leaves the original audit trace unchanged/u,
  );
});
