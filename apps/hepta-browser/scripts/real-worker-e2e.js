#!/usr/bin/env node

import { createHash } from "node:crypto";
import http from "node:http";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { browserActionDigest } from "../src/action.js";
import { FileBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";
import {
  LinuxBubblewrapLauncher,
  SubprocessBrowserDriver,
} from "../src/worker-driver.js";

const workerPath = resolve(process.argv[2] ?? "");
if (!process.argv[2]) {
  throw new Error("usage: real-worker-e2e.js WORKER_BINARY");
}

const sha256 = (value) =>
  createHash("sha256").update(value).digest("hex");
const fileDigest = async (path) => sha256(await readFile(path));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const workerDigest = await fileDigest(workerPath);
const bwrapPath = "/usr/bin/bwrap";
const prlimitPath = "/usr/bin/prlimit";
const bwrapDigest = await fileDigest(bwrapPath);
const prlimitDigest = await fileDigest(prlimitPath);
const root = await mkdtemp(join(tmpdir(), "hepta-servo-real-e2e-"));

let forbiddenHits = 0;
const forbidden = http.createServer((_req, res) => {
  forbiddenHits += 1;
  res.writeHead(200, { "content-type": "text/plain" });
  res.end("forbidden");
});
await new Promise((resolveListen) => forbidden.listen(0, "127.0.0.1", resolveListen));
const forbiddenPort = forbidden.address().port;

const seen = [];
const authorized = http.createServer((req, res) => {
  seen.push(req.url);
  if (req.url === "/") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(`<!doctype html>
      <html><head><title>Hepta Browser E2E</title></head>
      <body>
        <form action="/done" method="get">
          <label>Query <input name="q" type="text"></label>
          <button type="submit">Submit</button>
        </form>
        <div id="state">ready</div>
      </body></html>`);
    return;
  }
  if (req.url?.startsWith("/done")) {
    const url = new URL(req.url, "http://127.0.0.1");
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(`<!doctype html><html><body><h1>submitted:${url.searchParams.get("q") ?? ""}</h1></body></html>`);
    return;
  }
  if (req.url === "/redirect-escape") {
    res.writeHead(302, {
      location: `http://127.0.0.1:${forbiddenPort}/forbidden`,
    });
    res.end();
    return;
  }
  res.writeHead(404, { "content-type": "text/plain" });
  res.end("not found");
});
await new Promise((resolveListen) => authorized.listen(0, "127.0.0.1", resolveListen));
const port = authorized.address().port;
const origin = `http://127.0.0.1:${port}`;

const D = (name) => sha256(Buffer.from(name, "utf8"));
const PROFILE_GRANT = D("profile-grant");
const MANIFEST = D("browser-manifest");
const WITNESS = D("verified-use-witness");
const AUTHORITY_EPOCH = 7;

const authority = {
  async withVerifiedUse(request, consumer) {
    return consumer({
      authorized: true,
      witnessDigest: WITNESS,
      authorityEpoch: request.authorityEpoch,
      requestDigest: request.requestDigest,
    });
  },
};

const driver = new SubprocessBrowserDriver({
  workerPath,
  workerDigest,
  profileRoot: join(root, "profiles"),
  launcher: new LinuxBubblewrapLauncher({
    bwrapPath,
    bwrapDigest,
    prlimitPath,
    prlimitDigest,
  }),
});
const journal = new FileBrowserOperationJournal(join(root, "browser.journal"));
const host = new BrowserProfileHost({
  driver,
  authority,
  journal,
  driverCallTimeoutMs: 30_000,
});

const grantFor = (action, finalPayloadDigest, suffix) => ({
  grantDigest: D(`effect-grant-${suffix}`),
  action,
  destinationOrigin: origin,
  finalPayloadDigest,
  authorityEpoch: AUTHORITY_EPOCH,
  expiresAtMs: Date.now() + 120_000,
});

const operationFor = ({ operationId, pageGeneration, typedAction, effectGrantDigest }) => ({
  profileId: "profile.e2e",
  principalId: "principal.e2e",
  generation: 1,
  operationId,
  pageGeneration,
  typedAction,
  destinationOrigin: origin,
  finalPayloadDigest: browserActionDigest(typedAction),
  effectGrantDigest,
  authorityEpoch: AUTHORITY_EPOCH,
  deadlineMs: Date.now() + 60_000,
});

async function settle(operation, receipt) {
  if (receipt.terminalObserved === true) return receipt;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const next = await host.reconcileOperation(operation);
    if (next.terminalObserved === true) return next;
    await sleep(25);
  }
  throw new Error(`operation ${operation.operationId} did not become terminal`);
}

async function observeUntil(predicate) {
  let lastError;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const observation = await host.observePage({
        profileId: "profile.e2e",
        principalId: "principal.e2e",
        generation: 1,
        observationBudget: 64 * 1024,
      });
      if (predicate(observation)) return observation;
    } catch (error) {
      lastError = error;
    }
    await sleep(25);
  }
  throw lastError ?? new Error("page observation did not reach expected state");
}

let session;
try {
  const navigate = Object.freeze({
    kind: "navigate",
    url: `${origin}/`,
    policyDigest: D("policy"),
    expectedRevision: 1,
  });
  const navigateGrant = grantFor("navigate", browserActionDigest(navigate), "navigate");
  session = await host.openProfile({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    manifestDigest: MANIFEST,
    grantDigest: PROFILE_GRANT,
    generation: 1,
    expiresAtMs: Date.now() + 120_000,
    allowedOrigins: [origin],
    allowedNetworkAddresses: ["127.0.0.1"],
    effectGrants: [navigateGrant],
  });

  const navigateOperation = operationFor({
    operationId: "operation.navigate",
    pageGeneration: 0,
    typedAction: navigate,
    effectGrantDigest: navigateGrant.grantDigest,
  });
  const navigated = await settle(
    navigateOperation,
    await host.navigateOrAct(navigateOperation),
  );
  if (navigated.status !== "succeeded") {
    throw new Error(`initial navigation failed: ${JSON.stringify(navigated)}`);
  }

  let page = await observeUntil((value) =>
    value.semanticObservation?.visibleText?.includes("Submit"),
  );
  const controls = page.semanticObservation.controls ?? [];
  const inputControl = controls.find(
    (control) => control.tag === "input" && control.type === "text",
  );
  const submitControl = controls.find(
    (control) =>
      control.tag === "button" ||
      (control.tag === "input" && control.type === "submit"),
  );
  if (!inputControl?.selector || !submitControl?.selector) {
    throw new Error("semantic observation did not expose the expected form controls");
  }

  const typeAction = Object.freeze({
    kind: "type",
    selector: inputControl.selector,
    text: "hepta-e2e",
  });
  const typeGrant = grantFor("type", browserActionDigest(typeAction), "type");
  await host.admitEffectGrant({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    effectGrant: typeGrant,
  });
  const typeOperation = operationFor({
    operationId: "operation.type",
    pageGeneration: page.pageGeneration,
    typedAction: typeAction,
    effectGrantDigest: typeGrant.grantDigest,
  });
  const typed = await settle(typeOperation, await host.navigateOrAct(typeOperation));
  if (typed.status !== "succeeded") {
    throw new Error(`type failed: ${JSON.stringify(typed)}`);
  }

  page = await observeUntil((value) =>
    Array.isArray(value.semanticObservation?.controls),
  );
  const refreshedSubmit = page.semanticObservation.controls.find(
    (control) =>
      control.tag === "button" ||
      (control.tag === "input" && control.type === "submit"),
  );
  if (!refreshedSubmit?.selector) {
    throw new Error("submit control disappeared after type");
  }
  const clickAction = Object.freeze({
    kind: "click",
    selector: refreshedSubmit.selector,
  });
  const clickGrant = grantFor("click", browserActionDigest(clickAction), "click");
  await host.admitEffectGrant({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    effectGrant: clickGrant,
  });
  const clickOperation = operationFor({
    operationId: "operation.click",
    pageGeneration: page.pageGeneration,
    typedAction: clickAction,
    effectGrantDigest: clickGrant.grantDigest,
  });
  const clicked = await settle(clickOperation, await host.navigateOrAct(clickOperation));
  if (clicked.status !== "succeeded") {
    throw new Error(`click failed: ${JSON.stringify(clicked)}`);
  }

  const submitted = await observeUntil((value) =>
    value.semanticObservation?.visibleText?.includes("submitted:hepta-e2e"),
  );
  if (!submitted.semanticObservation.visibleText.includes("submitted:hepta-e2e")) {
    throw new Error("form navigation did not preserve the typed value");
  }
  if (!seen.some((path) => path === "/done?q=hepta-e2e")) {
    throw new Error(`authorized server did not observe the expected GET form submission: ${seen.join(",")}`);
  }

  const redirectAction = Object.freeze({
    kind: "navigate",
    url: `${origin}/redirect-escape`,
    policyDigest: D("policy"),
    expectedRevision: 2,
  });
  const redirectGrant = grantFor(
    "navigate",
    browserActionDigest(redirectAction),
    "redirect",
  );
  await host.admitEffectGrant({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    effectGrant: redirectGrant,
  });
  const redirectOperation = operationFor({
    operationId: "operation.redirect",
    pageGeneration: submitted.pageGeneration,
    typedAction: redirectAction,
    effectGrantDigest: redirectGrant.grantDigest,
  });
  await settle(
    redirectOperation,
    await host.navigateOrAct(redirectOperation),
  );
  await sleep(50);
  if (forbiddenHits !== 0) {
    throw new Error("redirect escape reached the forbidden origin");
  }

  const closed = await host.closeProfile({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
  });
  if (closed.terminalObserved !== true) {
    throw new Error("Browser profile did not close terminally");
  }

  process.stdout.write(
    JSON.stringify({
      schema: "hepta.browser.real-servo-e2e.v1",
      workerSha256: workerDigest,
      open: true,
      navigate: true,
      observe: true,
      type: true,
      click: true,
      formNavigationObserved: true,
      redirectEscapeDenied: forbiddenHits === 0,
      durableTerminalDrain: true,
      close: true,
    }) + "\n",
  );
} finally {
  await new Promise((resolveClose) => authorized.close(resolveClose));
  await new Promise((resolveClose) => forbidden.close(resolveClose));
  await rm(root, { recursive: true, force: true });
}
