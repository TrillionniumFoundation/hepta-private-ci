import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
  copyFile,
  mkdir,
  mkdtemp,
  writeFile,
  rm,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { buildService } from "../scripts/build-service.mjs";

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
  const workerSource = join(root, "worker-source");
  const serviceSource = join(root, "service-source");
  await mkdir(workerSource);
  await mkdir(join(serviceSource, "scripts"), { recursive: true });
  await mkdir(join(serviceSource, "src"));
  for (const path of ["scripts/build-service.mjs", "package-lock.json"]) {
    await copyFile(
      fileURLToPath(new URL("../" + path, import.meta.url)),
      join(serviceSource, path),
    );
  }
  await writeFile(
    join(serviceSource, "src", "agentd-service-main.js"),
    'import { createHash } from "node:crypto";\nimport { value } from "./effect.js";\nconsole.log(createHash("sha256").update(value).digest("hex"));\n',
  );
  await writeFile(
    join(serviceSource, "src", "effect.js"),
    'export const value = "reviewed effect";\n',
  );
  const serviceReceipt = await buildService({
    outputPath: join(root, "hepta-browser-service.mjs"),
    sourceRoot: join(serviceSource, "src"),
  });
  await chmod(join(root, "hepta-browser-service.mjs"), 0o600);
  await chmod(join(root, "hepta-browser-service.mjs.receipt.json"), 0o600);
  await json("topology.json", topology);
  await json("pin.json", {
    upstream_commit: PIN,
    upstream_repository: "servo/servo",
  });
  await writeFile(
    join(workerSource, "Cargo.toml"),
    `[dependencies.servo]\ngit = "https://github.com/servo/servo.git"\nrev = "${PIN}"\ndefault-features = false\n`,
  );
  await json("cargo-metadata.json", metadata());
  await writeFile(join(root, "cargo-lock-source.txt"), "committed\n");
  await writeFile(join(root, "Cargo.lock"), "reviewed dependency lock");
  await writeFile(join(workerSource, "Cargo.lock"), "reviewed dependency lock");
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
    serviceSha256: serviceReceipt.bundleSha256,
    serviceReceiptSha256: hash(JSON.stringify(serviceReceipt) + "\n"),
    reproducibleIndependentBuilds: true,
    reproducibleServiceBuilds: true,
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
        join(workerSource, "Cargo.toml"),
        "--service-source-root",
        serviceSource,
        ...args,
      ],
      { encoding: "utf8", timeout: 5000 },
    );
  return {
    root,
    workerSource,
    serviceSource,
    serviceReceipt,
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
    "serviceSha256",
    "serviceReceiptSha256",
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

test("service evidence rejects a self-consistent bundle substitution and omitted dependency", async (t) => {
  const f = await fixture(t);
  assert.equal(f.verify().status, 0);
  const substitutedBundle = 'console.log("unreviewed effect");\n';
  const substitutedReceipt = {
    ...f.serviceReceipt,
    bundleSha256: hash(substitutedBundle),
  };
  await writeFile(join(f.root, "hepta-browser-service.mjs"), substitutedBundle);
  await f.json("hepta-browser-service.mjs.receipt.json", substitutedReceipt);
  await f.json("build-receipt.json", {
    ...f.receipt,
    serviceSha256: hash(substitutedBundle),
    serviceReceiptSha256: hash(JSON.stringify(substitutedReceipt)),
  });
  const substituted = f.verify();
  assert.notEqual(substituted.status, 0);
  assert.match(substituted.stderr, /differs from source rebuild/);

  await rm(join(f.root, "hepta-browser-service.mjs"));
  await rm(join(f.root, "hepta-browser-service.mjs.receipt.json"));
  await buildService({
    outputPath: join(f.root, "hepta-browser-service.mjs"),
    sourceRoot: join(f.serviceSource, "src"),
  });
  await chmod(join(f.root, "hepta-browser-service.mjs.receipt.json"), 0o600);
  const omitted = {
    ...f.serviceReceipt,
    inputs: f.serviceReceipt.inputs.filter(
      (item) => item.path !== "src/effect.js",
    ),
  };
  await f.json("hepta-browser-service.mjs.receipt.json", omitted);
  await f.json("build-receipt.json", {
    ...f.receipt,
    serviceReceiptSha256: hash(JSON.stringify(omitted)),
  });
  const missing = f.verify();
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /differs from complete source rebuild/);
});

test("service evidence binds imported source, build recipe and dependency lock to checkout", async (t) => {
  const f = await fixture(t);
  for (const [path, pattern] of [
    ["src/effect.js", /source input digest mismatch/],
    ["scripts/build-service.mjs", /buildRecipeSha256 mismatch/],
    ["package-lock.json", /packageLockSha256 mismatch/],
  ]) {
    const selected = join(f.serviceSource, path);
    const backup = selected + ".backup";
    await copyFile(selected, backup);
    await writeFile(selected, "changed source");
    const result = f.verify();
    assert.notEqual(result.status, 0, path);
    assert.match(result.stderr, pattern);
    await copyFile(backup, selected);
  }
  await writeFile(join(f.workerSource, "Cargo.lock"), "unreviewed source lock");
  const result = f.verify();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /lock differs from checked-out source/);
});

test("service evidence refuses missing entrypoints, duplicate paths, traversal and external code", async (t) => {
  const f = await fixture(t);
  const malicious = [
    {
      inputs: f.serviceReceipt.inputs.filter(
        (item) => item.path !== "src/agentd-service-main.js",
      ),
    },
    { inputs: [...f.serviceReceipt.inputs, f.serviceReceipt.inputs[0]] },
    {
      inputs: [
        { path: "src/../outside.js", sha256: hash("outside") },
        ...f.serviceReceipt.inputs,
      ],
    },
    { externalModules: ["file:///ambient/code.mjs"] },
  ];
  for (const delta of malicious) {
    const receipt = { ...f.serviceReceipt, ...delta };
    await f.json("hepta-browser-service.mjs.receipt.json", receipt);
    await f.json("build-receipt.json", {
      ...f.receipt,
      serviceReceiptSha256: hash(JSON.stringify(receipt)),
    });
    assert.notEqual(f.verify().status, 0);
  }
  await rm(join(f.root, "hepta-browser-service.mjs.receipt.json"));
  assert.notEqual(f.verify().status, 0);
});

test("evidence refuses oversized bundles and rejects special files without waiting for a writer", async (t) => {
  const f = await fixture(t);
  const bundle = join(f.root, "hepta-browser-service.mjs");
  const oversized = Buffer.alloc(8 * 1024 * 1024 + 1);
  await writeFile(bundle, oversized);
  await f.json("build-receipt.json", {
    ...f.receipt,
    serviceSha256: hash(oversized),
  });
  const rejected = f.verify();
  assert.equal(rejected.error, undefined);
  assert.notEqual(rejected.status, 0);
  assert.match(rejected.stderr, /bounded regular file/);
  if (process.platform !== "linux") return;
  await rm(bundle);
  assert.equal(spawnSync("mkfifo", [bundle]).status, 0);
  const special = f.verify();
  assert.equal(special.error, undefined);
  assert.notEqual(special.status, 0);
  assert.match(special.stderr, /bounded regular file/);
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
