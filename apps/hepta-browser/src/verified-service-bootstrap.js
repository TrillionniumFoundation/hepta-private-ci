#!/usr/bin/env node

import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { open, realpath } from "node:fs/promises";
import { dirname, isAbsolute, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const MANIFEST_SCHEMA = "hepta.browser.service-closure-manifest.v1";
const EXPECTED_MANIFEST_SHA256 =
  "352940dbff09c0fdeaeba74ea6019522815aaf51c1611e10757d818347cc31b6";
const MAX_MANIFEST_BYTES = 256 * 1024;
const MAX_MODULE_BYTES = 16 * 1024 * 1024;
const GIT_BLOB = /^[0-9a-f]{40}$/;
const BOOTSTRAP_PATH = fileURLToPath(import.meta.url);
const APP_ROOT = resolve(dirname(BOOTSTRAP_PATH), "..");
const MANIFEST_PATH = resolve(APP_ROOT, "service-manifest.json");

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function exactKeys(value, expected, name) {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((key, index) => key !== wanted[index])) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function gitBlobId(bytes) {
  const header = Buffer.from(`blob ${bytes.length}\0`, "utf8");
  return createHash("sha1").update(header).update(bytes).digest("hex");
}

function safeRelativePath(value, name) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 512 ||
    isAbsolute(value) ||
    value.includes("\\") ||
    value.split("/").some((part) => part.length === 0 || part === "." || part === "..")
  ) {
    throw new TypeError(`${name} must be a canonical bounded relative path`);
  }
  return value;
}

async function readRegularNoFollow(path, maximum, name) {
  const noFollow = constants.O_NOFOLLOW ?? 0;
  const handle = await open(path, constants.O_RDONLY | noFollow);
  try {
    const info = await handle.stat();
    if (!info.isFile() || info.size < 1 || info.size > maximum) {
      throw new TypeError(`${name} must be a bounded regular file`);
    }
    return await handle.readFile();
  } finally {
    await handle.close();
  }
}

async function verifyClosure() {
  if ((await realpath(APP_ROOT)) !== APP_ROOT) {
    throw new TypeError("Browser service root contains a symlink");
  }
  const manifestBytes = await readRegularNoFollow(
    MANIFEST_PATH,
    MAX_MANIFEST_BYTES,
    "Browser service manifest",
  );
  if (sha256(manifestBytes) !== EXPECTED_MANIFEST_SHA256) {
    throw new TypeError("Browser service manifest digest mismatch");
  }

  let manifest;
  try {
    manifest = JSON.parse(manifestBytes.toString("utf8"));
  } catch {
    throw new TypeError("Browser service manifest is not valid JSON");
  }
  requireRecord(manifest, "Browser service manifest");
  exactKeys(manifest, ["entry", "files", "schema", "schemaVersion"], "Browser service manifest");
  if (manifest.schema !== MANIFEST_SCHEMA || manifest.schemaVersion !== 1) {
    throw new TypeError("Browser service manifest schema is unsupported");
  }

  const files = requireRecord(manifest.files, "Browser service manifest files");
  const entries = Object.entries(files);
  if (entries.length < 1 || entries.length > 128) {
    throw new TypeError("Browser service manifest file count is outside bounds");
  }
  const entry = safeRelativePath(manifest.entry, "Browser service entry");
  if (!Object.hasOwn(files, entry)) {
    throw new TypeError("Browser service entry is absent from the verified closure");
  }

  for (const [relativePath, expectedBlob] of entries) {
    const safePath = safeRelativePath(relativePath, "Browser service module path");
    if (typeof expectedBlob !== "string" || !GIT_BLOB.test(expectedBlob)) {
      throw new TypeError("Browser service module identity is not a Git blob ID");
    }
    const absolutePath = resolve(APP_ROOT, safePath);
    if (!absolutePath.startsWith(`${APP_ROOT}${sep}`)) {
      throw new TypeError("Browser service module escaped the application root");
    }
    const bytes = await readRegularNoFollow(
      absolutePath,
      MAX_MODULE_BYTES,
      `Browser service module ${safePath}`,
    );
    if (gitBlobId(bytes) !== expectedBlob) {
      throw new TypeError(`Browser service module digest mismatch: ${safePath}`);
    }
  }

  return resolve(APP_ROOT, entry);
}

const entryPath = await verifyClosure();
await import(pathToFileURL(entryPath).href);
