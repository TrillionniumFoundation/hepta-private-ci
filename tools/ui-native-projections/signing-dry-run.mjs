#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const read = (path) => readFileSync(resolve(ROOT, path), "utf8");

const plist = read("apps/hepta-native/packaging/macos/Info.plist");
const manifest = read("apps/hepta-native/packaging/windows/app.manifest");
const desktop = read("apps/hepta-native/packaging/linux/hepta-native.desktop");
const packaging = read("apps/hepta-native/packaging/README.md");

const checks = {
  macosBundleIdentity:
    plist.includes("<key>CFBundleIdentifier</key>") &&
    plist.includes("org.trillionnium.hepta.native"),
  macosMinimumVersion:
    plist.includes("<key>LSMinimumSystemVersion</key>") &&
    plist.includes("<string>14.0</string>"),
  windowsAsInvoker: manifest.includes('level="asInvoker"'),
  windowsPerMonitorV2: manifest.includes("PerMonitorV2"),
  linuxDesktopLauncher:
    desktop.includes("Type=Application") && desktop.includes("Exec=hepta-native"),
  unsignedTruth:
    packaging.includes("unsigned development packages") &&
    packaging.includes("production signing") &&
    packaging.includes("release authorization"),
};

const failed = Object.entries(checks).filter(([, value]) => !value).map(([name]) => name);
if (failed.length > 0) {
  throw new Error(`signing/notarization dry-run prerequisites failed: ${failed.join(", ")}`);
}

console.log(
  JSON.stringify(
    {
      schema: "hepta.ui.native.signing-dry-run.v1",
      checks,
      commands: {
        macos: [
          "codesign --deep --force --options runtime --sign <developer-id> <app>",
          "xcrun notarytool submit <archive> --wait --keychain-profile <profile>",
          "xcrun stapler staple <app>",
        ],
        windows: [
          "signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256 /a <artifact>",
          "signtool verify /pa /all <artifact>",
        ],
        linux: [
          "sha256sum <artifact>",
          "distribution-specific package/repository signing under release-owner custody",
        ],
      },
      credentialsUsed: false,
      productionSigningObserved: false,
      releaseAuthorized: false,
    },
    null,
    2,
  ),
);
