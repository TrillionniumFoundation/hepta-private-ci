import { execFileSync, spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "dist");
const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
let requestCount = 0;
let reconcileCount = 0;
let connectCount = 0;
let expireSnapshotOnce = false;
let currentSessionId = null;

function findChrome() {
  if (process.env.HEPTA_CHROME) return process.env.HEPTA_CHROME;
  for (const candidate of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    try {
      return execFileSync("which", [candidate], { encoding: "utf8" }).trim();
    } catch {}
  }
  throw new Error("Chromium/Chrome executable is required for browser E2E qualification");
}

function json(res, status, value) {
  const body = JSON.stringify(value);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  res.end(body);
}

async function readJson(req) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 64 * 1024) throw new Error("request too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const securityHeaders = JSON.parse(await readFile(join(dist, "security-headers.json"), "utf8"));
const baseIndex = await readFile(join(dist, "index.html"), "utf8");
const e2eDriver = `
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(predicate, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = predicate();
    if (value) return value;
    await sleep(20);
  }
  throw new Error("browser E2E wait timed out");
}
async function waitForAsync(predicate, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await sleep(20);
  }
  throw new Error("browser E2E async wait timed out");
}
const stats = () => fetch("/api/ui-control/e2e-stats", { cache: "no-store" }).then((response) => response.json());
try {
  const root = document.querySelector("#app");
  await waitFor(() => root.getAttribute("data-hepta-ready") === "true");

  const retry = [...document.querySelectorAll("button")].find((button) => button.textContent.startsWith("Retry "));
  if (!retry) throw new Error("retry control missing");
  retry.focus();
  retry.click();
  retry.click();
  const dialog = await waitFor(() => document.querySelector("dialog[data-hepta-confirm='operation']"));
  if (!dialog.getAttribute("aria-labelledby")) throw new Error("confirmation dialog missing accessible name binding");
  const exact = dialog.querySelector("pre[aria-label='Exact request payload']");
  if (!exact || !exact.textContent.includes("request_retry")) throw new Error("exact immutable request is not visible");
  dialog.querySelector("[data-hepta-confirm-submit='true']").click();
  await waitFor(() => document.querySelector("[role='status'],[role='alert']")?.textContent.includes("pending"));
  if ((await stats()).requestCount !== 1) throw new Error("rapid duplicate click crossed transport more than once");
  const pendingStorageKey = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
    .find((key) => key?.startsWith("hepta.ui.control.pending."));
  if (!pendingStorageKey || pendingStorageKey.includes("e2e.operator")) {
    throw new Error("pending store key is not bound through opaque persistence-domain identity");
  }
  const focused = document.activeElement;
  if (!focused || focused.textContent !== "Retry runtime.agentd") throw new Error("focus was not restored to the initiating action");
  if (root.getAttribute("aria-busy") !== "false") throw new Error("busy state was not cleared");

  const quarantine = [...document.querySelectorAll("button")].find((button) => button.textContent.startsWith("Quarantine "));
  quarantine.click();
  const blockedDialog = await waitFor(() => document.querySelector("dialog[data-hepta-confirm='operation']"));
  window.dispatchEvent(new Event("offline"));
  await waitFor(() => root.getAttribute("data-hepta-ready") === "false");
  blockedDialog.querySelector("[data-hepta-confirm-submit='true']").click();
  await sleep(700);
  if (root.getAttribute("data-hepta-ready") !== "false") {
    throw new Error("offline mutation block was cleared by a stale polling response");
  }
  if ((await stats()).requestCount !== 1) throw new Error("offline confirmation crossed transport");
  const blockedButtons = [...document.querySelectorAll("#app button")];
  if (!blockedButtons.length || blockedButtons.some((button) => !button.disabled)) {
    throw new Error("offline event did not disable mutating controls");
  }

  window.dispatchEvent(new Event("online"));
  await waitForAsync(async () => (await stats()).connectCount >= 2);
  await waitFor(() => root.getAttribute("data-hepta-ready") === "true");
  const recoveredRetry = [...document.querySelectorAll("button")].find((button) => button.textContent.startsWith("Retry "));
  if (!recoveredRetry || recoveredRetry.disabled) throw new Error("online recovery did not restore coherent controls");

  const beforeSuspend = (await stats()).connectCount;
  const pageHide = new Event("pagehide");
  Object.defineProperty(pageHide, "persisted", { value: true });
  window.dispatchEvent(pageHide);
  await sleep(100);
  if ((await stats()).connectCount !== beforeSuspend) {
    throw new Error("pagehide suspension unexpectedly reopened a runtime session");
  }
  const pageShow = new Event("pageshow");
  Object.defineProperty(pageShow, "persisted", { value: true });
  window.dispatchEvent(pageShow);
  await waitForAsync(async () => (await stats()).connectCount >= beforeSuspend + 1);
  await waitFor(() => root.getAttribute("data-hepta-ready") === "true");

  await fetch("/api/ui-control/e2e-expire-session", { cache: "no-store" });
  await waitForAsync(async () => (await stats()).connectCount >= beforeSuspend + 2, 7000);
  await waitFor(() => root.getAttribute("data-hepta-ready") === "true", 7000);
  if ((await stats()).requestCount !== 1) throw new Error("session recovery replayed a mutation");

  document.body.setAttribute("data-e2e-status", "pass");
} catch (error) {
  document.body.setAttribute("data-e2e-status", "fail");
  document.body.setAttribute("data-e2e-error", String(error?.message ?? error));
}
`;

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://127.0.0.1");
    if (url.pathname === "/api/ui-control/bootstrap") {
      return json(res, 200, {
        endpointId: "runtime.1",
        protocolVersion: 1,
        manifestDigest: D1,
        basePath: "/api/ui-control",
        persistenceNamespace: "e2e.operator",
        snapshotPollMs: 500,
        requestTimeoutMs: 5_000,
      });
    }
    if (url.pathname === "/api/ui-control/csrf") return json(res, 200, { token: "e2e-csrf" });
    if (url.pathname === "/api/ui-control/connect") {
      if (req.headers["x-hepta-csrf"] !== "e2e-csrf") return json(res, 403, { error: "csrf" });
      const body = await readJson(req);
      connectCount += 1;
      currentSessionId = `session.e2e.${connectCount}`;
      return json(res, 200, {
        authenticated: true,
        sessionId: currentSessionId,
        connectionGeneration: connectCount,
        protocolVersion: body.protocolVersion,
      });
    }
    if (url.pathname === "/api/ui-control/snapshot") {
      if (expireSnapshotOnce) {
        expireSnapshotOnce = false;
        return json(res, 401, { error: "expired" });
      }
      if (!currentSessionId) return json(res, 401, { error: "no session" });
      return json(res, 200, {
        sessionId: currentSessionId,
        connectionGeneration: connectCount,
        generation: 7 + connectCount,
        revision: 9 + connectCount,
        digest: D2,
        modules: [{ moduleId: "runtime.agentd", status: "ready", revision: 4 + connectCount, digest: D3 }],
      });
    }
    if (url.pathname === "/api/ui-control/request") {
      if (req.headers["x-hepta-csrf"] !== "e2e-csrf") return json(res, 403, { error: "csrf" });
      const body = await readJson(req);
      requestCount += 1;
      return json(res, 200, {
        accepted: true,
        method: body.method,
        sessionId: body.request.sessionId,
        connectionGeneration: body.request.connectionGeneration,
        runtimeGeneration: body.request.runtimeGeneration,
        operationId: body.request.operationId,
        semanticDigest: body.request.semanticDigest,
      });
    }
    if (url.pathname === "/api/ui-control/reconcile") {
      if (req.headers["x-hepta-csrf"] !== "e2e-csrf") return json(res, 403, { error: "csrf" });
      await readJson(req);
      reconcileCount += 1;
      return json(res, 200, null);
    }
    if (url.pathname === "/api/ui-control/close") {
      if (req.headers["x-hepta-csrf"] !== "e2e-csrf") return json(res, 403, { error: "csrf" });
      await readJson(req);
      return json(res, 200, { closed: true });
    }
    if (url.pathname === "/api/ui-control/e2e-expire-session") {
      expireSnapshotOnce = true;
      return json(res, 200, { armed: true });
    }
    if (url.pathname === "/api/ui-control/e2e-stats") {
      return json(res, 200, { requestCount, reconcileCount, connectCount });
    }
    if (url.pathname === "/e2e-driver.js") {
      res.writeHead(200, { "content-type": "text/javascript; charset=utf-8", "cache-control": "no-store" });
      return res.end(e2eDriver);
    }

    let path = url.pathname === "/" ? "/index.html" : url.pathname;
    path = normalize(path).replace(/^([.][.][/\\])+/, "");
    const full = join(dist, path.replace(/^\//, ""));
    if (!full.startsWith(dist)) return json(res, 404, { error: "not found" });
    let body = await readFile(full);
    if (path === "/index.html") {
      body = Buffer.from(baseIndex.replace("</body>", '  <script type="module" src="/e2e-driver.js"></script>\n</body>'));
    }
    for (const [name, value] of Object.entries(securityHeaders)) res.setHeader(name, value);
    const type = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".webmanifest": "application/manifest+json" }[extname(path)] ?? "application/octet-stream";
    res.writeHead(200, { "content-type": `${type}; charset=utf-8`, "content-length": body.length, "cache-control": "no-store" });
    res.end(body);
  } catch (error) {
    json(res, 500, { error: String(error?.message ?? error) });
  }
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
const chrome = findChrome();
const chromeArgs = [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--disable-dev-shm-usage",
  "--disable-background-networking",
  "--disable-default-apps",
  "--disable-extensions",
  "--disable-sync",
  "--metrics-recording-only",
  "--no-first-run",
  "--virtual-time-budget=9000",
  "--dump-dom",
  `http://127.0.0.1:${address.port}/`,
];
const child = spawn(chrome, chromeArgs, { stdio: ["ignore", "pipe", "pipe"] });
let stdout = "";
let stderr = "";
child.stdout.setEncoding("utf8");
child.stderr.setEncoding("utf8");
child.stdout.on("data", (chunk) => { stdout += chunk; });
child.stderr.on("data", (chunk) => { stderr += chunk; });
const exit = await new Promise((resolve, reject) => {
  const timeout = setTimeout(() => {
    child.kill("SIGKILL");
    reject(new Error("Chrome E2E timed out"));
  }, 35_000);
  child.on("error", (error) => { clearTimeout(timeout); reject(error); });
  child.on("close", (code, signal) => { clearTimeout(timeout); resolve({ code, signal }); });
});
server.close();
if (exit.code !== 0) {
  throw new Error(`Chrome E2E failed: ${stderr || `exit ${exit.code ?? exit.signal}`}`);
}
if (!stdout.includes('data-e2e-status="pass"')) {
  const match = stdout.match(/data-e2e-error="([^"]*)"/);
  throw new Error(`browser E2E assertion failed${match ? `: ${match[1]}` : ""}`);
}
console.log("PASS_HEPTA_UI_CONTROL_BROWSER_E2E");
