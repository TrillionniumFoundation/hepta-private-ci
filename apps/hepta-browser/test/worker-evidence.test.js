import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const verifier = fileURLToPath(
  new URL("../scripts/verify-worker-evidence.py", import.meta.url),
);
const PIN = "8".repeat(40);
const SHA = "a".repeat(40);
const TREE = "b".repeat(40);
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const topology = {
  source: { repository: "servo/servo", commit: PIN },
  decision: {
    initiallyForbiddenServoFeatures: ["default", "webgpu"],
    requiredServoFeatures: ["bundled"],
  },
};
const metadata = () => ({
  packages: [
    {
      id: "servo-id",
      name: "servo",
      source: `git+https://github.com/servo/servo.git?rev=${PIN}#${PIN}`,
    },
  ],
  resolve: { nodes: [{ id: "servo-id", features: ["bundled"] }] },
});

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "hepta-worker-evidence-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const json = (name, value) =>
    writeFile(join(root, name), JSON.stringify(value));
  await json("topology.json", topology);
  await json("pin.json", {
    upstream_commit: PIN,
    upstream_repository: "servo/servo",
  });
  await writeFile(
    join(root, "Cargo.toml"),
    `[dependencies.servo]\ngit = "https://github.com/servo/servo.git"\nrev = "${PIN}"\ndefault-features = false\n`,
  );
  await json("cargo-metadata.json", metadata());
  await writeFile(join(root, "cargo-lock-source.txt"), "committed\n");
  await writeFile(join(root, "Cargo.lock"), "reviewed dependency lock");
  await writeFile(join(root, "hepta-servo-worker"), "exact worker");
  await writeFile(join(root, "hepta-servo-worker.spdx.json"), "exact SBOM");
  const workerSha = hash("exact worker");
  const receipt = {
    schema: "hepta.browser.servo-worker-build-receipt.v1",
    sourceSha: SHA,
    sourceTree: TREE,
    servoPin: PIN,
    workerSha256: workerSha,
    cargoLockSha256: hash("reviewed dependency lock"),
    sbomSha256: hash("exact SBOM"),
    reproducibleIndependentBuilds: true,
    linuxSandboxProbe: {
      externalNetworkDenied: true,
      hostSecretHidden: true,
      generalHostBinariesHidden: true,
      privateProfileWritable: true,
    },
    realWorkerSmoke: {
      workerSha256: workerSha,
      currentPinWorkerBooted: true,
      privateProtocolRoundTrip: true,
      sandboxedStartStop: true,
    },
  };
  await json("build-receipt.json", receipt);
  const run = (...args) =>
    spawnSync(
      "python3",
      [
        verifier,
        "--topology",
        join(root, "topology.json"),
        "--pin-manifest",
        join(root, "pin.json"),
        "--worker-manifest",
        join(root, "Cargo.toml"),
        ...args,
      ],
      { encoding: "utf8", timeout: 5000 },
    );
  return {
    root,
    json,
    receipt,
    run,
    verify: () =>
      run(
        "--receipt-root",
        root,
        "--source-sha",
        SHA,
        "--source-tree",
        TREE,
        "--worker-sha",
        workerSha,
      ),
  };
}

test("feature admission reads resolved Cargo features and rejects quoted-tree escape cases", async (t) => {
  const f = await fixture(t);
  const check = () => f.run("--metadata", join(f.root, "cargo-metadata.json"));
  assert.equal(check().status, 0);
  for (const feature of ["webdriver_server", "webgpu", "default"]) {
    const data = metadata();
    data.resolve.nodes[0].features.push(feature);
    await f.json("cargo-metadata.json", data);
    assert.notEqual(check().status, 0, feature);
  }
  const data = metadata();
  data.packages.push({ id: "webdriver-id", name: "webdriver_server" });
  await f.json("cargo-metadata.json", data);
  assert.notEqual(check().status, 0);
});

test("receipt binds source tree, pin, dependency lock, SBOM and smoke to selected artifact", async (t) => {
  const f = await fixture(t);
  assert.equal(f.verify().status, 0);
  for (const field of [
    "sourceSha",
    "sourceTree",
    "servoPin",
    "workerSha256",
    "cargoLockSha256",
    "sbomSha256",
  ]) {
    await f.json("build-receipt.json", {
      ...f.receipt,
      [field]: "0".repeat(64),
    });
    assert.notEqual(f.verify().status, 0, field);
  }
  await f.json("build-receipt.json", {
    ...f.receipt,
    realWorkerSmoke: {
      ...f.receipt.realWorkerSmoke,
      workerSha256: "0".repeat(64),
    },
  });
  assert.notEqual(f.verify().status, 0);
  await f.json("build-receipt.json", f.receipt);
  await writeFile(
    join(f.root, "cargo-lock-source.txt"),
    "generated-candidate\n",
  );
  assert.notEqual(f.verify().status, 0);
});

test("receipt rejects tampered files and missing resolved current-pin Servo", async (t) => {
  const f = await fixture(t);
  await writeFile(join(f.root, "hepta-servo-worker.spdx.json"), "changed SBOM");
  assert.notEqual(f.verify().status, 0);
  const data = metadata();
  data.packages[0].source = "registry+https://example.invalid";
  await f.json("cargo-metadata.json", data);
  assert.notEqual(
    f.run("--metadata", join(f.root, "cargo-metadata.json")).status,
    0,
  );
  data.packages[0].source = `git+https://attacker.invalid/servo.git?rev=${PIN}#${PIN}`;
  await f.json("cargo-metadata.json", data);
  assert.notEqual(
    f.run("--metadata", join(f.root, "cargo-metadata.json")).status,
    0,
  );
  await f.json("cargo-metadata.json", metadata());
  await f.json("pin.json", {
    upstream_commit: "0".repeat(40),
    upstream_repository: "servo/servo",
  });
  assert.notEqual(
    f.run("--metadata", join(f.root, "cargo-metadata.json")).status,
    0,
  );
});
