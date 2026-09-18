#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { LinuxBubblewrapLauncher } from "../src/worker-driver.js";

function waitForExit(child) {
  return new Promise((resolve, reject) => {
    let stderr = "";
    child.stderr?.setEncoding("utf8");
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) resolve({ code, signal, stderr });
      else reject(new Error(`sandbox probe failed: code=${code} signal=${signal} stderr=${stderr}`));
    });
  });
}

const root = await mkdtemp(join(tmpdir(), "hepta-browser-bwrap-probe-"));
const profileDir = join(root, "profile");
const probeSource = join(root, "probe.c");
const probePath = join(root, "probe");
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

try {
  const launcher = new LinuxBubblewrapLauncher({ bwrapPath: "/usr/bin/bwrap" });
  await mkdir(profileDir, { mode: 0o700 });
  const child = launcher.spawn({ workerPath: probePath, profileDir });
  child.stdin.end();
  await waitForExit(child);
  const marker = await readFile(join(profileDir, "sandbox-probe.ok"), "utf8");
  if (marker !== "isolated\n") throw new Error("sandbox probe marker mismatch");
  process.stdout.write(JSON.stringify({
    schema: "hepta.browser.linux-sandbox-probe.v2",
    externalNetworkDenied: true,
    hostSecretHidden: true,
    generalHostBinariesHidden: true,
    privateProfileWritable: true,
    posture: launcher.posture,
  }) + "\n");
} finally {
  await rm(hostSecret, { force: true });
  await rm(root, { recursive: true, force: true });
}
