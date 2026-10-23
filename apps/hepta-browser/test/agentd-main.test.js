import assert from "node:assert/strict";
import test from "node:test";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildService } from "../scripts/build-service.mjs";

import {
  AgentdBrowserFrameDecoder,
  buildAgentdBrowserFrame,
  encodeAgentdBrowserFrame,
} from "../src/agentd-protocol.js";

for (const variant of ["source", "bundle"])
  test(
    `real ${variant} service accepts its owner instance and kills its worker after parent EOF`,
    {
      skip: process.platform !== "linux",
      timeout: 15_000,
    },
    async (t) => {
      const root = await realpath(
        await mkdtemp(join(tmpdir(), "hepta-agentd-main-")),
      );
      const launcherPath = join(root, "fixture-launcher.mjs");
      const workerPath = join(root, "fixture-worker.bin");
      const workerBytes = Buffer.from("artifact-bound fixture worker", "utf8");
      const protocol = new URL("../src/worker-protocol.js", import.meta.url)
        .href;
      await writeFile(workerPath, workerBytes, { mode: 0o500 });
      // This launcher is a protocol fixture, not Bubblewrap/Servo qualification.
      // The worker deliberately stays alive even after its stdin ends, so only
      // the service's explicit shutdown can make the service process exit.
      await writeFile(
        launcherPath,
        `#!${process.execPath}
import { WorkerFrameDecoder, buildWorkerFrame, encodeWorkerFrame } from ${JSON.stringify(protocol)};
const decoder = new WorkerFrameDecoder();
let sequence = 1;
process.stdin.on("data", (chunk) => {
  for (const request of decoder.push(chunk)) {
    process.stdout.write(encodeWorkerFrame(buildWorkerFrame({
      sessionId: request.sessionId, generation: request.generation,
      sequence: sequence++, kind: "response", requestId: request.requestId,
      payload: { ok: true, observation: { started: true } },
    })));
  }
});
setInterval(() => {}, 1_000);
`,
        { mode: 0o700 },
      );

      let servicePath = fileURLToPath(
        new URL("../src/agentd-service-main.js", import.meta.url),
      );
      if (variant === "bundle") {
        servicePath = join(root, "standalone", "service.mjs");
        await buildService({ outputPath: servicePath });
      }
      const child = spawn(process.execPath, [servicePath], {
        env: {
          HEPTA_BROWSER_WORKER_PATH: workerPath,
          HEPTA_BROWSER_WORKER_SHA256: createHash("sha256")
            .update(workerBytes)
            .digest("hex"),
          HEPTA_BROWSER_PROFILE_ROOT: join(root, "profiles"),
          HEPTA_BROWSER_JOURNAL_PATH: join(root, "journal", "operations.jsonl"),
          HEPTA_BROWSER_BWRAP_PATH: launcherPath,
        },
        stdio: ["pipe", "pipe", "pipe"],
      });
      let workerPid;
      let diagnostics = "";
      child.stderr.on("data", (chunk) => {
        diagnostics += chunk;
      });
      t.after(async () => {
        child.kill("SIGKILL");
        if (workerPid !== undefined) {
          try {
            process.kill(workerPid, "SIGKILL");
          } catch {}
        }
        await rm(root, { recursive: true, force: true });
      });

      const decoder = new AgentdBrowserFrameDecoder();
      const response = new Promise((resolve, reject) => {
        child.stdout.on("data", (chunk) => {
          try {
            for (const frame of decoder.push(chunk)) resolve(frame);
          } catch (error) {
            reject(error);
          }
        });
        child.once("error", reject);
        child.once("exit", (code) =>
          reject(new Error(`service exited ${code}: ${diagnostics}`)),
        );
      });
      const manifestDigest = "1".repeat(64);
      child.stdin.write(
        encodeAgentdBrowserFrame(
          buildAgentdBrowserFrame({
            sequence: 1,
            kind: "request",
            requestId: "request.open",
            payload: {
              method: "open_profile",
              input: {
                profileId: "profile.main",
                principalId: "principal.main",
                generation: 1,
                manifestDigest,
                grantDigest: manifestDigest,
                expiresAtMs: Date.now() + 60_000,
                allowedOrigins: [],
                effectGrants: [],
              },
            },
          }),
        ),
      );
      const frame = await response;
      assert.equal(frame.payload.ok, true, frame.payload.error);
      assert.match(frame.payload.result.processId, /^servo\.pid\.[1-9][0-9]*$/);
      workerPid = Number(frame.payload.result.processId.split(".").at(-1));
      const exited = once(child, "exit");
      child.stdin.end();
      assert.deepEqual(await exited, [0, null], diagnostics);
      assert.equal(diagnostics, "");
      assert.throws(() => process.kill(workerPid, 0), { code: "ESRCH" });
      workerPid = undefined;
    },
  );
