#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

function parseCargoLock(text) {
  const blocks = text.split(/\n\[\[package\]\]\n/).slice(1);
  return blocks.map((block) => {
    const field = (name) => block.match(new RegExp(`^${name} = "([^"]+)"$`, "m"))?.[1] ?? null;
    return {
      name: field("name"),
      version: field("version"),
      source: field("source"),
      checksum: field("checksum"),
    };
  }).filter((pkg) => pkg.name && pkg.version);
}

const outIndex = process.argv.indexOf("--out");
const out = outIndex >= 0 ? process.argv[outIndex + 1] : null;
if (!out) throw new Error("usage: sbom.mjs --out <path>");

const appLockPath = resolve(ROOT, "apps/hepta-native/Cargo.lock");
const ownerLockPath = resolve(ROOT, "codex-rs/Cargo.lock");
const locks = [
  ["apps-hepta-native", appLockPath],
  ["codex-rs-owner-closure", ownerLockPath],
];

const packages = [];
for (const [scope, path] of locks) {
  const text = readFileSync(path, "utf8");
  for (const item of parseCargoLock(text)) {
    const identity = sha256(
      `${scope}\0${item.name}\0${item.version}\0${item.source ?? ""}\0${item.checksum ?? ""}`,
    ).slice(0, 12);
    const id = `SPDXRef-Package-${scope}-${item.name.replace(/[^A-Za-z0-9.-]/g, "-")}-${item.version}-${identity}`;
    packages.push({
      SPDXID: id,
      name: item.name,
      versionInfo: item.version,
      downloadLocation: item.source ?? "NOASSERTION",
      filesAnalyzed: false,
      checksums: item.checksum
        ? [{ algorithm: "SHA256", checksumValue: item.checksum }]
        : [],
      externalRefs: [{ referenceCategory: "OTHER", referenceType: "hepta-scope", referenceLocator: scope }],
    });
  }
}

packages.sort((a, b) =>
  `${a.name}\0${a.versionInfo}\0${a.SPDXID}`.localeCompare(
    `${b.name}\0${b.versionInfo}\0${b.SPDXID}`,
  ),
);

const created = new Date().toISOString();
const document = {
  spdxVersion: "SPDX-2.3",
  dataLicense: "CC0-1.0",
  SPDXID: "SPDXRef-DOCUMENT",
  name: "hepta-ui-native-source-sbom",
  documentNamespace: `https://trillionnium.org/spdx/ui-native/${sha256(JSON.stringify(packages))}`,
  creationInfo: {
    created,
    creators: ["Tool: tools/ui-native-projections/sbom.mjs"],
  },
  packages,
  annotations: [
    {
      annotationType: "OTHER",
      annotator: "Tool: tools/ui-native-projections/sbom.mjs",
      annotationDate: created,
      comment:
        "Source dependency SBOM generated from committed Cargo locks. Binary signing and release authorization are external gates.",
    },
  ],
};

const output = resolve(ROOT, out);
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, `${JSON.stringify(document, null, 2)}\n`, "utf8");
console.log(output);
