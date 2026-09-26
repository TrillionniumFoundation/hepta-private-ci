#!/usr/bin/env node
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import http from "node:http";
import { chmod, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { browserActionDigest } from "../src/action.js";
import { FileBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";
import { LinuxBubblewrapLauncher, SubprocessBrowserDriver } from "../src/worker-driver.js";

const workerPath = resolve(process.argv[2] ?? "");
if (!process.argv[2]) throw new Error("usage: real-browser-soak.js WORKER_BINARY");
const CYCLES = 32;
const RSS_PEAK_GROWTH_LIMIT_KIB = 512 * 1024;
const RSS_TERMINAL_GROWTH_LIMIT_KIB = 256 * 1024;
const sha = (value) => createHash("sha256").update(value).digest("hex");
const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const WITNESS = "a".repeat(64);

const server = http.createServer((_request, response) => {
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(`<!doctype html><html><head><title>soak</title></head>
  <body style="height:8000px"><button aria-label="stable">stable</button>
  ${Array.from({ length: 200 }, (_, i) => `<p>row-${i}</p>`).join("")}
  </body></html>`);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

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
function grant(id, action, payloadDigest) {
  return {
    grantDigest: sha(`grant:${id}`),
    action,
    destinationOrigin: origin,
    finalPayloadDigest: payloadDigest,
    authorityEpoch: 7,
    expiresAtMs: Date.now() + 300_000,
  };
}
function operation(operationId, pageGeneration, typedAction, effectGrant) {
  return {
    profileId: "profile.soak",
    principalId: "principal.soak",
    generation: 1,
    operationId,
    pageGeneration,
    typedAction,
    destinationOrigin: origin,
    finalPayloadDigest: browserActionDigest(typedAction),
    effectGrantDigest: effectGrant.grantDigest,
    authorityEpoch: 7,
    deadlineMs: Date.now() + 30_000,
  };
}
async function metrics(processId) {
  const match = /^servo\.pid\.(\d+)\.[A-Za-z0-9-]+$/.exec(processId);
  const pid = match ? Number(match[1]) : NaN;
  if (!Number.isSafeInteger(pid) || pid < 1) throw new Error("invalid Servo process id");
  const status = await readFile(`/proc/${pid}/status`, "utf8");
  const match = /^VmRSS:\s+(\d+)\s+kB$/m.exec(status);
  if (!match) throw new Error("VmRSS missing from worker process status");
  return { pid, rssKiB: Number(match[1]), fdCount: (await readdir(`/proc/${pid}/fd`)).length };
}

const workerBytes = await readFile(workerPath);
const [bwrapBytes, prlimitBytes] = await Promise.all([
  readFile("/usr/bin/bwrap"),
  readFile("/usr/bin/prlimit"),
]);
const root = await mkdtemp(join(tmpdir(), "hepta-browser-soak-"));
await chmod(root, 0o700);

try {
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: sha(workerBytes),
    profileRoot: join(root, "profiles"),
    launcher: new LinuxBubblewrapLauncher({
      bwrapPath: "/usr/bin/bwrap",
      bwrapDigest: sha(bwrapBytes),
      prlimitPath: "/usr/bin/prlimit",
      prlimitDigest: sha(prlimitBytes),
    }),
    allowPrivateNetworkForTests: true,
  });
  const host = new BrowserProfileHost({
    driver,
    authority,
    journal: new FileBrowserOperationJournal(join(root, "journal.log")),
    driverCallTimeoutMs: 15_000,
  });
  const navigate = { kind: "navigate", url: `${origin}/soak`, policyDigest: D1, expectedRevision: 1 };
  const navGrant = grant("navigate", "navigate", browserActionDigest(navigate));
  const session = await host.openProfile({
    profileId: "profile.soak",
    principalId: "principal.soak",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: Date.now() + 300_000,
    allowedOrigins: [origin],
    effectGrants: [navGrant],
  });
  const navInput = operation("soak.navigate", 0, navigate, navGrant);
  let navReceipt = await host.navigateOrAct(navInput);
  for (let i = 0; i < 750 && !navReceipt.terminalObserved; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 20));
    navReceipt = await host.reconcileOperation(navInput);
  }
  assert.equal(navReceipt.terminalObserved, true);
  assert.equal(navReceipt.status, "succeeded");

  const scroll = { kind: "scroll", deltaX: 0, deltaY: 5 };
  const scrollGrant = grant("scroll", "scroll", browserActionDigest(scroll));
  await host.admitEffectGrant({
    profileId: "profile.soak",
    principalId: "principal.soak",
    generation: 1,
    effectGrant: scrollGrant,
  });
  const samples = [await metrics(session.processId)];
  for (let cycle = 0; cycle < CYCLES; cycle += 1) {
    const page = await host.observePage({
      profileId: "profile.soak",
      principalId: "principal.soak",
      generation: 1,
      observationBudget: 65_536,
    });
    const receipt = await host.navigateOrAct(
      operation(`soak.scroll.${cycle}`, page.pageGeneration, scroll, scrollGrant),
    );
    assert.equal(receipt.terminalObserved, true);
    assert.equal(receipt.status, "succeeded");
    samples.push(await metrics(session.processId));
  }
  await host.closeProfile({ profileId: "profile.soak", principalId: "principal.soak", generation: 1 });

  const rss = samples.map((sample) => sample.rssKiB);
  const fds = samples.map((sample) => sample.fdCount);
  const result = {
    schema: "hepta.browser.real-soak.v1",
    cycles: CYCLES,
    workerSha256: sha(workerBytes),
    rssKiB: { first: rss[0], last: rss.at(-1), min: Math.min(...rss), max: Math.max(...rss) },
    fdCount: { first: fds[0], last: fds.at(-1), min: Math.min(...fds), max: Math.max(...fds) },
    rssPeakGrowthLimitKiB: RSS_PEAK_GROWTH_LIMIT_KIB,
    rssTerminalGrowthLimitKiB: RSS_TERMINAL_GROWTH_LIMIT_KIB,
    boundedRssGrowth:
      Math.max(...rss) <= rss[0] + RSS_PEAK_GROWTH_LIMIT_KIB &&
      rss.at(-1) <= rss[0] + RSS_TERMINAL_GROWTH_LIMIT_KIB,
    boundedFdGrowth: Math.max(...fds) <= fds[0] + 32,
  };
  assert.equal(result.boundedRssGrowth, true);
  assert.equal(result.boundedFdGrowth, true);
  process.stdout.write(JSON.stringify(result) + "\n");
} finally {
  await new Promise((resolve) => server.close(resolve));
  await rm(root, { recursive: true, force: true });
}
