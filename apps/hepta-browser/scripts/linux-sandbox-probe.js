#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  access,
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { LinuxBubblewrapLauncher } from "../src/worker-driver.js";

function waitForExit(child) {
  return new Promise((resolve, reject) => {
    let stderr = "";
    child.stderr?.setEncoding("utf8");
    child.stderr?.on("data", (chunk) => {
      stderr += chunk;
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) resolve({ code, signal, stderr });
      else {
        reject(
          new Error(
            `sandbox probe failed: code=${code} signal=${signal} stderr=${stderr}`,
          ),
        );
      }
    });
  });
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    throw error;
  }
}

async function waitUntil(predicate, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`${label} did not become true before timeout`);
}

const root = await mkdtemp(join(tmpdir(), "hepta-browser-bwrap-probe-"));
const profileDir = join(root, "profile");
const probeSource = join(root, "probe.c");
const probePath = join(root, "probe");
const lingerSource = join(root, "linger.c");
const lingerPath = join(root, "linger");
const parentHelper = join(root, "parent-helper.mjs");
const hostSecret = `/var/tmp/hepta-browser-host-secret-${randomUUID()}`;

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
  `  int sock = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);\n` +
  `  if (sock < 0) return 14;\n` +
  `  struct sockaddr_in addr; memset(&addr, 0, sizeof(addr));\n` +
  `  addr.sin_family = AF_INET; addr.sin_port = htons(53);\n` +
  `  if (inet_pton(AF_INET, "1.1.1.1", &addr.sin_addr) != 1) return 15;\n` +
  `  if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) == 0) return 16;\n` +
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
  { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
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
  { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
);
if (lingerCompiled.status !== 0) {
  throw new Error(
    `parent-death probe compilation failed: ${lingerCompiled.stderr}`,
  );
}
await chmod(lingerPath, 0o500);

await writeFile(
  parentHelper,
  `import { spawn } from "node:child_process";\n` +
    `import { access, readFile } from "node:fs/promises";\n` +
    `const [command, encodedArgs, marker] = process.argv.slice(2);\n` +
    `async function descendants(pid) {\n` +
    `  const found = []; const queue = [pid];\n` +
    `  while (queue.length) {\n` +
    `    const current = queue.shift(); let text = "";\n` +
    `    try { text = await readFile("/proc/" + current + "/task/" + current + "/children", "utf8"); } catch {}\n` +
    `    for (const token of text.trim().split(/\\s+/).filter(Boolean)) {\n` +
    `      const childPid = Number.parseInt(token, 10);\n` +
    `      if (Number.isSafeInteger(childPid) && childPid > 1 && !found.includes(childPid)) { found.push(childPid); queue.push(childPid); }\n` +
    `    }\n` +
    `  }\n` +
    `  return found;\n` +
    `}\n` +
    `const child = spawn(command, JSON.parse(encodedArgs), { env: {}, stdio: "ignore", shell: false });\n` +
    `child.unref();\n` +
    `const deadline = Date.now() + 5000;\n` +
    `while (Date.now() < deadline) {\n` +
    `  try {\n` +
    `    await access(marker);\n` +
    `    const childPids = await descendants(child.pid);\n` +
    `    if (childPids.length === 0) { child.kill("SIGKILL"); process.exit(3); }\n` +
    `    process.stdout.write(JSON.stringify({ bwrapPid: child.pid, descendantPids: childPids }) + "\\n");\n` +
    `    process.exit(0);\n` +
    `  } catch {}\n` +
    `  await new Promise((resolve) => setTimeout(resolve, 20));\n` +
    `}\n` +
    `child.kill("SIGKILL");\n` +
    `process.exit(2);\n`,
  { mode: 0o500 },
);

try {
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
  const child = launcher.spawn({ workerPath: probePath, profileDir });
  child.stdin.end();
  await waitForExit(child);
  const marker = await readFile(join(profileDir, "sandbox-probe.ok"), "utf8");
  if (marker !== "isolated\n") throw new Error("sandbox probe marker mismatch");

  const deathProfileDir = join(root, "profile-parent-death");
  await mkdir(deathProfileDir, { mode: 0o700 });
  const readyMarker = join(deathProfileDir, "parent-death.ready");
  const deathSpec = launcher.spawnSpec({
    workerPath: lingerPath,
    profileDir: deathProfileDir,
  });
  const helper = spawn(
    process.execPath,
    [
      parentHelper,
      deathSpec.command,
      JSON.stringify(deathSpec.args),
      readyMarker,
    ],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  let helperStdout = "";
  let helperStderr = "";
  helper.stdout.setEncoding("utf8");
  helper.stderr.setEncoding("utf8");
  helper.stdout.on("data", (chunk) => {
    helperStdout += chunk;
  });
  helper.stderr.on("data", (chunk) => {
    helperStderr += chunk;
  });
  const helperExit = await new Promise((resolve, reject) => {
    helper.once("error", reject);
    helper.once("exit", (code, signal) => resolve({ code, signal }));
  });
  if (helperExit.code !== 0) {
    throw new Error(
      `parent-death launcher failed: code=${helperExit.code} signal=${helperExit.signal} stderr=${helperStderr}`,
    );
  }
  await access(readyMarker);
  let processReport;
  try {
    processReport = JSON.parse(helperStdout.trim());
  } catch {
    throw new Error(
      "parent-death launcher did not report canonical process identities",
    );
  }
  const bwrapPid = processReport?.bwrapPid;
  const descendantPids = processReport?.descendantPids;
  if (
    !Number.isSafeInteger(bwrapPid) ||
    bwrapPid < 2 ||
    !Array.isArray(descendantPids) ||
    descendantPids.length === 0 ||
    descendantPids.some((pid) => !Number.isSafeInteger(pid) || pid < 2)
  ) {
    throw new Error("parent-death launcher reported invalid process identities");
  }
  await waitUntil(
    () => !processExists(bwrapPid),
    5_000,
    "bubblewrap parent-death cleanup",
  );
  await waitUntil(
    () => descendantPids.every((pid) => !processExists(pid)),
    5_000,
    "sandbox descendant cleanup",
  );

  process.stdout.write(JSON.stringify({
    schema: "hepta.browser.linux-sandbox-probe.v4",
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
} finally {
  await rm(hostSecret, { force: true });
  await rm(root, { recursive: true, force: true });
}
