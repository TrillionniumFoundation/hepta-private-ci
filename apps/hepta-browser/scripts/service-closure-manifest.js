#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

const MAX_FILE_BYTES = 16 * 1024 * 1024;
const ROLE_PATHS = Object.freeze({
  agentd_service_main: "src/agentd-service-main.js",
  agentd_service: "src/agentd-service.js",
  agentd_protocol: "src/agentd-protocol.js",
  action: "src/action.js",
  effect_egress_gate: "src/effect-egress-gate.js",
  effect_network_driver: "src/effect-network-driver.js",
  egress_broker: "src/egress-broker.js",
  journal: "src/journal.js",
  observation_redactor: "src/observation-redactor.js",
  persisted_reconciler: "src/persisted-reconciler.js",
  runtime: "src/runtime.js",
  runtime_host: "src/runtime-host.js",
  runtime_contract: "src/runtime-contract.js",
  runtime_boundary: "src/runtime-boundary.js",
  worker_driver: "src/worker-driver.js",
  worker_protocol: "src/worker-protocol.js",
});

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}

const [rootArgument, outputArgument] = process.argv.slice(2);
if (!rootArgument || !outputArgument) {
  fail("usage: service-closure-manifest.js BROWSER_ROOT OUTPUT.json");
} else {
  const requestedRoot = resolve(rootArgument);
  const root = realpathSync(requestedRoot);
  if (root !== requestedRoot) {
    throw new TypeError("Browser root must be a canonical non-symlink path");
  }
  const output = resolve(outputArgument);
  if (!isAbsolute(output)) {
    throw new TypeError("closure output path must be absolute");
  }

  const entries = {};
  for (const [role, relativePath] of Object.entries(ROLE_PATHS)) {
    const path = resolve(join(root, relativePath));
    if (!path.startsWith(`${root}/`)) {
      throw new TypeError(`closure role ${role} escaped the Browser root`);
    }
    const info = lstatSync(path);
    if (
      info.isSymbolicLink() ||
      !info.isFile() ||
      info.size < 1 ||
      info.size > MAX_FILE_BYTES
    ) {
      throw new TypeError(`closure role ${role} is not a bounded regular file`);
    }
    if (realpathSync(path) !== path) {
      throw new TypeError(`closure role ${role} contains a symlink`);
    }
    const bytes = readFileSync(path);
    entries[role] = {
      path,
      sha256: createHash("sha256").update(bytes).digest("hex"),
    };
  }

  const manifest = {
    schema: "hepta.browser.service-closure.v1",
    version: 1,
    entries,
  };
  writeFileSync(output, `${JSON.stringify(manifest, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
}
