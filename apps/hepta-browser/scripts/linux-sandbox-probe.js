#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
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
const probePath = join(root, "probe.py");
const hostSecret = `/var/tmp/hepta-browser-host-secret-${randomUUID()}`;

await writeFile(hostSecret, "must-not-be-visible\n", { mode: 0o600 });
await writeFile(
  probePath,
  `#!/usr/bin/python3\n` +
  `import os, pathlib, socket, sys\n` +
  `secret = pathlib.Path(${JSON.stringify(hostSecret)})\n` +
  `if secret.exists():\n    raise SystemExit("host secret unexpectedly visible")\n` +
  `if os.environ.get("HOME") != "/hepta-profile":\n    raise SystemExit("HOME is not private profile")\n` +
  `if os.environ.get("TMPDIR") != "/tmp":\n    raise SystemExit("TMPDIR is not private tmp")\n` +
  `sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n` +
  `sock.settimeout(1.0)\n` +
  `try:\n` +
  `    sock.connect(("1.1.1.1", 53))\n` +
  `except OSError:\n` +
  `    pass\n` +
  `else:\n` +
  `    raise SystemExit("external network unexpectedly reachable")\n` +
  `finally:\n` +
  `    sock.close()\n` +
  `pathlib.Path("/hepta-profile/sandbox-probe.ok").write_text("isolated\\n", encoding="utf-8")\n`,
  { mode: 0o500 },
);
await chmod(probePath, 0o500);

try {
  const launcher = new LinuxBubblewrapLauncher({ bwrapPath: "/usr/bin/bwrap" });
  await import("node:fs/promises").then(({ mkdir }) => mkdir(profileDir, { mode: 0o700 }));
  const child = launcher.spawn({ workerPath: probePath, profileDir });
  child.stdin.end();
  await waitForExit(child);
  const marker = await readFile(join(profileDir, "sandbox-probe.ok"), "utf8");
  if (marker !== "isolated\n") throw new Error("sandbox probe marker mismatch");
  process.stdout.write(JSON.stringify({
    schema: "hepta.browser.linux-sandbox-probe.v1",
    externalNetworkDenied: true,
    hostSecretHidden: true,
    privateProfileWritable: true,
    posture: launcher.posture,
  }) + "\n");
} finally {
  await rm(hostSecret, { force: true });
  await rm(root, { recursive: true, force: true });
}
