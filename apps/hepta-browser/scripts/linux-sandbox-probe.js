#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { observeProbeProcess, snapshotProbeTree, waitForProbeTreeExit } from "./sandbox-probe-process.js";

import { LinuxBubblewrapLauncher } from "../src/worker-driver.js";

const root = await mkdtemp(join(tmpdir(), "hepta-browser-bwrap-probe-"));
const profileDir = join(root, "profile");
const probeSource = join(root, "probe.c");
const probePath = join(root, "probe");
const lingerSource = join(root, "linger.c");
const lingerPath = join(root, "linger");
const parentHelper = fileURLToPath(new URL("./sandbox-parent-helper.js", import.meta.url));
const hostSecret = `/var/tmp/hepta-browser-host-secret-${randomUUID()}`;

let phase = "prepare-canaries";
let helper;
let helperObserved;
let child;
let childObserved;
try {
  await writeFile(hostSecret, "must-not-be-visible\n", { mode: 0o600 });
  await writeFile(
    probeSource,
    `#include <arpa/inet.h>\n` +
    `#include <errno.h>\n` +
    `#include <fcntl.h>\n` +
    `#include <netinet/in.h>\n` +
    `#include <stdlib.h>\n` +
    `#include <string.h>\n` +
    `#include <sys/socket.h>\n` +
    `#include <sys/stat.h>\n` +
    `#include <sys/resource.h>\n` +
    `#include <sys/types.h>\n` +
    `#include <unistd.h>\n` +
    `int main(void) {\n` +
    `  const char *secret = ${JSON.stringify(hostSecret)};\n` +
    `  const char *home = getenv("HOME");\n` +
    `  const char *tmp = getenv("TMPDIR");\n` +
    `  if (access(secret, F_OK) == 0) return 10;\n` +
    `  if (!home || strcmp(home, "/hepta-profile") != 0) return 11;\n` +
    `  if (!tmp || strcmp(tmp, "/tmp") != 0) return 12;\n` +
    `  if (access("/usr/bin/sh", F_OK) == 0 || access("/usr/bin/python3", F_OK) == 0) return 13;\n` +
    `  struct rlimit limit;\n` +
    `  if (getrlimit(RLIMIT_AS, &limit) != 0 || limit.rlim_cur != 8589934592ULL || limit.rlim_max != 8589934592ULL) return 20;\n` +
    `  if (getrlimit(RLIMIT_CPU, &limit) != 0 || limit.rlim_cur != 300ULL || limit.rlim_max != 300ULL) return 21;\n` +
    `  if (getrlimit(RLIMIT_NOFILE, &limit) != 0 || limit.rlim_cur != 4096ULL || limit.rlim_max != 4096ULL) return 22;\n` +
    `  if (getrlimit(RLIMIT_NPROC, &limit) != 0 || limit.rlim_cur != 256ULL || limit.rlim_max != 256ULL) return 23;\n` +
    `  int sock = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);\n` +
    `  if (sock < 0) return 14;\n` +
    `  struct sockaddr_in addr; memset(&addr, 0, sizeof(addr));\n` +
    `  addr.sin_family = AF_INET; addr.sin_port = htons(53);\n` +
    `  if (inet_pton(AF_INET, "1.1.1.1", &addr.sin_addr) != 1) return 15;\n` +
    `  if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == 0) return 16;\n` +
    `  if (errno != ENETUNREACH && errno != EHOSTUNREACH && errno != EACCES && errno != EPERM) return 24;\n` +
    `  close(sock);\n` +
    `  int out = open("/hepta-profile/sandbox-probe.ok", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);\n` +
    `  if (out < 0) return 17;\n` +
    `  const char marker[] = "isolated\\n";\n` +
    `  if (write(out, marker, sizeof(marker) - 1) != (ssize_t)(sizeof(marker) - 1)) return 18;\n` +
    `  if (fsync(out) != 0) return 19;\n` +
    `  close(out);\n` +
    `  return 0;\n` +
    `}\n`,
    { mode: 0o600 },
  );
  const compiled = spawnSync(
    "/usr/bin/cc",
    ["-O2", "-fPIE", "-pie", "-Wl,-z,relro,-z,now", "-o", probePath, probeSource],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 30_000, maxBuffer: 65_536 },
  );
  if (compiled.status !== 0) {
    throw new Error(`sandbox probe compilation failed: ${compiled.stderr}`);
  }
  await chmod(probePath, 0o500);

  await writeFile(
    lingerSource,
    `#include <fcntl.h>\n` +
      `#include <signal.h>\n` +
      `#include <unistd.h>\n` +
      `int main(void) {\n` +
      `  int ready[2]; if (pipe(ready) != 0) return 33;\n` +
      `  pid_t child = fork(); if (child < 0) return 34;\n` +
      `  if (child == 0) { close(ready[0]); if (write(ready[1], "R", 1) != 1) return 35; close(ready[1]); for (;;) pause(); }\n` +
      `  close(ready[1]); char ack; if (read(ready[0], &ack, 1) != 1 || ack != 'R') return 36; close(ready[0]);\n` +
      `  int out = open("/hepta-profile/parent-death.ready", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);\n` +
      `  if (out < 0) return 30;\n` +
      `  const char marker[] = "ready\\n";\n` +
      `  if (write(out, marker, sizeof(marker) - 1) != (ssize_t)(sizeof(marker) - 1)) return 31;\n` +
      `  if (fsync(out) != 0) return 32;\n` +
      `  close(out);\n` +
      `  for (;;) pause();\n` +
      `}\n`,
    { mode: 0o600 },
  );
  const lingerCompiled = spawnSync(
    "/usr/bin/cc",
    ["-O2", "-fPIE", "-pie", "-Wl,-z,relro,-z,now", "-o", lingerPath, lingerSource],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 30_000, maxBuffer: 65_536 },
  );
  if (lingerCompiled.status !== 0) {
    throw new Error(
      `parent-death probe compilation failed: ${lingerCompiled.stderr}`,
    );
  }
  await chmod(lingerPath, 0o500);

  phase = "verify-launcher";
  const bwrapBytes = await readFile("/usr/bin/bwrap");
  const prlimitBytes = await readFile("/usr/bin/prlimit");
  const launcher = new LinuxBubblewrapLauncher({
    bwrapPath: "/usr/bin/bwrap",
    bwrapDigest: createHash("sha256").update(bwrapBytes).digest("hex"),
    prlimitPath: "/usr/bin/prlimit",
    prlimitDigest: createHash("sha256").update(prlimitBytes).digest("hex"),
  });
  await launcher.verify();
  await mkdir(profileDir, { mode: 0o700 });
  phase = "runtime-invariants";
  child = launcher.spawn({ workerPath: probePath, profileDir });
  childObserved = observeProbeProcess(child, { label: phase });
  child.stdin.end();
  const runtimeExit = await childObserved.completion;
  const marker = await readFile(join(profileDir, "sandbox-probe.ok"), "utf8");
  if (marker !== "isolated\n") throw new Error("sandbox probe marker mismatch");

  const deathProfileDir = join(root, "profile-parent-death");
  await mkdir(deathProfileDir, { mode: 0o700 });
  const readyMarker = join(deathProfileDir, "parent-death.ready");
  const deathSpec = launcher.spawnSpec({
    workerPath: lingerPath,
    profileDir: deathProfileDir,
  });
  phase = "parent-death-readiness";
  helper = spawn(process.execPath, [parentHelper, deathSpec.command,
    JSON.stringify(deathSpec.args), readyMarker], { env: {}, stdio: ["pipe", "pipe", "pipe"] });
  helperObserved = observeProbeProcess(helper, { label: phase, timeoutMs: 20_000 });
  const report = JSON.parse(await helperObserved.readyLine({ timeoutMs: 7_000 }));
  if (report.ready !== true || Object.keys(report).sort().join(",") !== "launcherPid,ready") {
    throw new Error("parent-death helper readiness schema mismatch");
  }
  // The helper remains alive here. No exit signal may precede this census;
  // empty/post-mortem PID lists cannot qualify descendant cleanup.
  const identities = await snapshotProbeTree(report.launcherPid);
  if (await readFile(readyMarker, "utf8") !== "ready\n") throw new Error("parent-death marker mismatch");
  phase = "parent-death-release";
  await new Promise((resolve, reject) => {
    helper.stdin.write("release\n", error => error ? reject(error) : resolve());
  });
  await helperObserved.completion;
  phase = "parent-death-exit-observation";
  await waitForProbeTreeExit(identities);

  process.stdout.write(JSON.stringify({
    schema: "hepta.browser.linux-sandbox-probe.v4",
    readinessAcknowledgedBeforeParentExit: true,
    observedHostProcessLifetimes: identities,
    runtimeExit: { code: runtimeExit.exit.code, signal: runtimeExit.exit.signal },
    externalNetworkDenied: true,
    hostSecretHidden: true,
    generalHostBinariesHidden: true,
    privateProfileWritable: true,
    resourceLimitsEnforced: true,
    resourceLimits: launcher.resourceLimits,
    parentDeathCleanupObserved: true,
    descendantCleanupObserved: true,
    posture: launcher.posture,
  }) + "\n");
} catch (error) {
  // Diagnostics are not a successful qualification receipt, especially on SIGKILL.
  process.stderr.write(JSON.stringify({ phase, message: error.message, probe: error.probe ?? null }) + "\n");
  throw error;
} finally {
  for (const [owned, observed] of [[helper, helperObserved], [child, childObserved]]) {
    if (owned && owned.exitCode === null && owned.signalCode === null) owned.kill("SIGKILL");
    if (observed) await observed.completion.catch(() => {});
  }
  await rm(hostSecret, { force: true });
  await rm(root, { recursive: true, force: true });
}
