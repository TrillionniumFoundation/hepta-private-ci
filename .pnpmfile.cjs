// Run before dependency resolution and before workspace prepare scripts.
// This hook changes no package metadata or dependency selection.
const { execFileSync } = require("node:child_process");
const path = require("node:path");
execFileSync(
  process.execPath,
  [path.join(__dirname, "scripts/verify-mcp-conformance-vendor.mjs")],
  { stdio: ["ignore", "pipe", "inherit"] },
);

module.exports = {
  hooks: {
    readPackage(pkg) {
      return pkg;
    },
  },
};
