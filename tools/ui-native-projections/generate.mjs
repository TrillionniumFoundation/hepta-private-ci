#!/usr/bin/env node
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = resolve(HERE, "../..");
export const OUTPUT_ROOT = join(REPO_ROOT, "docs/modules/ui.native/generated");

const API_OPERATIONS = [
  {
    id: "connect_runtime",
    path: "apps/hepta-native/src/runtime.rs",
    symbol: "pub fn connect_runtime(",
    boundary: "authenticated_session_bootstrap",
  },
  {
    id: "render_runtime_view",
    path: "apps/hepta-native/src/runtime.rs",
    symbol: "pub fn refresh_runtime_view(",
    boundary: "authenticated_monotonic_runtime_snapshot",
  },
  {
    id: "request_platform_capability",
    path: "apps/hepta-native/src/runtime.rs",
    symbol: "pub fn request_platform_capability(",
    boundary: "durable_final_use_authorized_effect",
  },
  {
    id: "reconcile_pending",
    path: "apps/hepta-native/src/runtime.rs",
    symbol: "pub fn reconcile_pending(",
    boundary: "crash_safe_non_replay_reconciliation",
  },
  {
    id: "apply_shell_update",
    path: "apps/hepta-native/src/updater.rs",
    symbol: "pub fn verify_and_stage(",
    boundary: "signed_predecessor_bound_staging",
  },
  {
    id: "confirm_running_update",
    path: "apps/hepta-native/src/updater.rs",
    symbol: "pub fn confirm_running_process(",
    boundary: "active_digest_and_runtime_health_confirmation",
  },
];

const TEST_PROFILES = [
  {
    id: "projection_tooling",
    command: "npm test",
    workingDirectory: "tools/ui-native-projections",
  },
  {
    id: "native_application",
    command: "cargo test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets",
    workingDirectory: ".",
  },
  {
    id: "gateway_authority",
    command:
      "cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-native-gateway -p codex-hepta-contracts -p codex-hepta-private-state --all-targets --all-features",
    workingDirectory: ".",
  },
  {
    id: "release_fault_profile",
    command: "hepta-native --qualification-e2e",
    workingDirectory: "packaged artifact",
  },
];

function read(root, path) {
  const absolute = join(root, path);
  if (!existsSync(absolute) || !statSync(absolute).isFile()) {
    throw new Error(`missing required source file: ${path}`);
  }
  return readFileSync(absolute, "utf8");
}

function requireMarker(root, path, marker) {
  const source = read(root, path);
  if (!source.includes(marker)) {
    throw new Error(`missing source marker ${JSON.stringify(marker)} in ${path}`);
  }
  return source;
}

function walkFiles(root, directory) {
  const base = join(root, directory);
  const output = [];
  const visit = (current) => {
    for (const name of readdirSync(current).sort()) {
      const absolute = join(current, name);
      const info = statSync(absolute);
      if (info.isDirectory()) {
        visit(absolute);
      } else if (info.isFile()) {
        output.push(relative(root, absolute).split(sep).join("/"));
      }
    }
  };
  visit(base);
  return output;
}

function enumBody(source, enumName) {
  const match = source.match(new RegExp(`pub enum ${enumName}\\s*\\{([\\s\\S]*?)\\n\\}`));
  if (!match) throw new Error(`unable to locate Rust enum ${enumName}`);
  return match[1];
}

function enumVariants(source, enumName) {
  return enumBody(source, enumName)
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => /^[A-Z][A-Za-z0-9_]*(?:\s*\{|,)/.test(line))
    .map((line) => line.match(/^([A-Z][A-Za-z0-9_]*)/)[1]);
}

function toSnake(value) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .toLowerCase();
}

function rustConstant(source, name) {
  const match = source.match(new RegExp(`pub const ${name}:\\s*usize\\s*=\\s*([0-9 *]+);`));
  if (!match) throw new Error(`unable to locate Rust constant ${name}`);
  const expression = match[1].trim();
  if (!/^[0-9 *]+$/.test(expression)) {
    throw new Error(`unsafe constant expression for ${name}`);
  }
  return expression
    .split("*")
    .map((part) => Number.parseInt(part.trim(), 10))
    .reduce((left, right) => left * right, 1);
}

function plistValue(source, key) {
  const match = source.match(
    new RegExp(`<key>${key}</key>\\s*<string>([^<]+)</string>`, "m"),
  );
  if (!match) throw new Error(`missing plist key ${key}`);
  return match[1];
}

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

export function stableJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

export function buildProjections(root = REPO_ROOT) {
  const runtime = read(root, "apps/hepta-native/src/runtime.rs");
  const updater = read(root, "apps/hepta-native/src/updater.rs");
  const model = read(root, "apps/hepta-native/src/model.rs");
  const cargo = read(root, "apps/hepta-native/Cargo.toml");
  const mac = read(root, "apps/hepta-native/packaging/macos/Info.plist");
  const windows = read(root, "apps/hepta-native/packaging/windows/app.manifest");
  const linux = read(root, "apps/hepta-native/packaging/linux/hepta-native.desktop");
  const packaging = read(root, "apps/hepta-native/packaging/README.md");
  const main = read(root, "apps/hepta-native/src/main.rs");
  const journal = read(root, "apps/hepta-native/src/journal.rs");
  const security = read(root, "apps/hepta-native/src/security.rs");

  for (const operation of API_OPERATIONS) {
    requireMarker(root, operation.path, operation.symbol);
  }
  for (const marker of [
    "OperationPhase::Prepared",
    "OperationPhase::Invoking",
    "OperationPhase::Indeterminate",
    "OperationPhase::Terminal",
  ]) {
    if (!runtime.includes(marker) && !journal.includes(marker)) {
      throw new Error(`durable operation state marker is missing: ${marker}`);
    }
  }
  for (const marker of [
    "KernelFinalUseGate",
    "platform_final_use_binding",
    "with_platform_use",
  ]) {
    if (!security.includes(marker) && !runtime.includes(marker)) {
      throw new Error(`final-use marker is missing: ${marker}`);
    }
  }
  if (!main.includes("fn run(")) {
    throw new Error("production bootstrap marker fn run( is missing");
  }
  if (!updater.includes("pub fn confirm_running_process(")) {
    throw new Error("runtime update confirmation is missing");
  }

  const actionVariants = enumVariants(model, "PlatformAction");
  const payloadVariants = new Set(enumVariants(model, "PlatformPayload"));
  const actions = actionVariants.map((variant) => {
    if (!payloadVariants.has(variant)) {
      throw new Error(`PlatformAction ${variant} has no matching PlatformPayload`);
    }
    return {
      id: toSnake(variant),
      rustVariant: variant,
      payloadVariant: variant,
      terminalReceiptRequired: true,
      finalUseGrantRequired: true,
    };
  });

  const testFiles = walkFiles(root, "apps/hepta-native/tests")
    .filter((path) => path.endsWith(".rs"))
    .map((path) => ({
      path,
      role: path.includes("/common/") ? "support" : "integration_test",
    }));

  const apiRegistry = {
    schema: "hepta.ui.native.api-registry.v1",
    canonicalImplementation: {
      language: "rust",
      productRoot: "apps/hepta-native",
      bootstrap: "apps/hepta-native/src/main.rs::run",
    },
    historyInheritance: {
      allowed: false,
      rule:
        "Only files and receipts bound to the current candidate source identity may establish capability.",
      retiredEntrypoints: [
        "apps/hepta-native/src/native.js",
        "apps/hepta-native/src/shell-runtime.js",
      ],
    },
    operations: API_OPERATIONS,
  };

  const testRegistry = {
    schema: "hepta.ui.native.test-registry.v1",
    sourceDiscovery: {
      root: "apps/hepta-native/tests",
      fileCount: testFiles.length,
      manifestDigest: sha256(stableJson(testFiles)),
    },
    files: testFiles,
    profiles: TEST_PROFILES,
    requiredEvidence: [
      "exact_head",
      "deterministic_synthetic_merge",
      "linux",
      "macos",
      "windows",
      "package_integrity",
      "fault_injection",
      "crash_restart_recovery",
      "accessibility_automation",
      "signing_dry_run",
    ],
  };

  const capabilityRegistry = {
    schema: "hepta.ui.native.capability-registry.v1",
    source: "apps/hepta-native/src/model.rs",
    actions,
    limits: {
      stableIdBytes: rustConstant(model, "MAX_STABLE_ID_BYTES"),
      copyTextBytes: rustConstant(model, "MAX_COPY_TEXT_BYTES"),
      notificationTitleBytes: rustConstant(
        model,
        "MAX_NOTIFICATION_TITLE_BYTES",
      ),
      notificationBodyBytes: rustConstant(
        model,
        "MAX_NOTIFICATION_BODY_BYTES",
      ),
    },
    bindingContext: [
      "endpoint_id",
      "session_id",
      "session_generation",
      "subject_id",
      "operation_id",
      "displayed_revision",
      "action",
      "payload_digest",
      "binding_digest",
      "grant_digest",
    ],
    durablePhases: ["prepared", "invoking", "indeterminate", "terminal"],
    terminalStatuses: ["succeeded", "failed", "rejected", "quarantined"],
  };

  for (const feature of ["accesskit", "wayland", "x11"]) {
    if (!cargo.includes(`"${feature}"`)) {
      throw new Error(`native Cargo feature ${feature} is missing`);
    }
  }
  for (const phrase of [
    "unsigned development packages",
    "production signing",
    "notarization",
    "release authorization",
  ]) {
    if (!packaging.toLowerCase().includes(phrase)) {
      throw new Error(`packaging truth is missing phrase: ${phrase}`);
    }
  }

  const platformMatrix = {
    schema: "hepta.ui.native.platform-matrix.v1",
    uiFramework: "eframe-0.36",
    accessibilityAdapter: "accesskit",
    windowPolicy: {
      singleProcess: true,
      concurrentPlatformEffects: "journal_linearized",
      sessionPolicy: "one authenticated runtime session incarnation per shell",
      multiWindowPolicy: "not admitted until shared journal ownership is proven",
    },
    platforms: [
      {
        id: "linux",
        runner: "ubuntu-24.04",
        packageShape: "AppDir deterministic unsigned ZIP",
        metadata: "apps/hepta-native/packaging/linux/hepta-native.desktop",
        launcher: linux.match(/^Exec=(.+)$/m)?.[1] ?? null,
        secretStore: "desktop keyring through codex-keyring-store",
        sandboxPolicy: "host policy; shell itself owns no domain authority",
        signingState: "external_evidence_gate",
      },
      {
        id: "macos",
        runner: "macos-15",
        packageShape: "app bundle deterministic unsigned ZIP",
        metadata: "apps/hepta-native/packaging/macos/Info.plist",
        minimumVersion: plistValue(mac, "LSMinimumSystemVersion"),
        bundleIdentifier: plistValue(mac, "CFBundleIdentifier"),
        secretStore: "Keychain through codex-keyring-store",
        entitlements: "release-owner supplied and independently reviewed",
        signingState: "developer_id_and_notarization_external_gate",
      },
      {
        id: "windows",
        runner: "windows-2025",
        packageShape: "application directory deterministic unsigned ZIP",
        metadata: "apps/hepta-native/packaging/windows/app.manifest",
        executionLevel: windows.includes('level="asInvoker"')
          ? "asInvoker"
          : null,
        dpiAwareness: windows.includes("PerMonitorV2")
          ? "PerMonitorV2"
          : null,
        longPathAware: windows.includes("<longPathAware") &&
          windows.includes(">true</longPathAware>"),
        secretStore: "Windows credential store through codex-keyring-store",
        signingState: "authenticode_external_gate",
      },
    ],
    automatedAccessibility: [
      "AccessKit adapter compiled in",
      "keyboard and focus paths covered by product qualification fixtures",
      "generated source projection rejects missing accessibility feature",
    ],
    physicalAcceptanceGates: [
      "screen_reader",
      "chinese_ime",
      "focus_restoration",
      "multi_monitor_dpi",
      "reduced_motion",
      "contrast",
    ],
  };

  return new Map([
    ["api-registry.json", apiRegistry],
    ["test-registry.json", testRegistry],
    ["capability-registry.json", capabilityRegistry],
    ["platform-matrix.json", platformMatrix],
  ]);
}

export function renderProjections(root = REPO_ROOT) {
  return new Map(
    [...buildProjections(root)].map(([name, value]) => [name, stableJson(value)]),
  );
}

export function writeGenerated(root = REPO_ROOT) {
  const output = join(root, "docs/modules/ui.native/generated");
  mkdirSync(output, { recursive: true });
  for (const [name, text] of renderProjections(root)) {
    writeFileSync(join(output, name), text, "utf8");
  }
}

export function verifyGenerated(root = REPO_ROOT) {
  const output = join(root, "docs/modules/ui.native/generated");
  const mismatches = [];
  for (const [name, expected] of renderProjections(root)) {
    const path = join(output, name);
    const actual = existsSync(path) ? readFileSync(path, "utf8") : null;
    if (actual !== expected) mismatches.push(name);
  }
  if (mismatches.length > 0) {
    throw new Error(`generated ui.native projections are stale: ${mismatches.join(", ")}`);
  }
}

function main() {
  const mode = process.argv[2];
  if (mode === "--write") {
    writeGenerated();
  } else if (mode === "--verify") {
    verifyGenerated();
  } else {
    throw new Error("usage: generate.mjs --write|--verify");
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
