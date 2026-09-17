import {
  closeSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { randomUUID } from "node:crypto";

const STORE_SCHEMA = "hepta.browser.profile-store.v1";

function clone(value) {
  return value === undefined ? undefined : structuredClone(value);
}

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function validateEnvelope(value) {
  requireRecord(value, "browser state store");
  if (value.schema !== STORE_SCHEMA || !Array.isArray(value.profiles)) {
    throw new TypeError("browser state store schema is unsupported");
  }
  const records = new Map();
  for (const profile of value.profiles) {
    requireRecord(profile, "browser profile record");
    if (typeof profile.profileId !== "string" || profile.profileId.length === 0) {
      throw new TypeError("browser profile record has invalid profileId");
    }
    if (records.has(profile.profileId)) {
      throw new TypeError("browser state store contains duplicate profileId");
    }
    records.set(profile.profileId, clone(profile));
  }
  return records;
}

export class MemoryBrowserStateStore {
  durable = false;
  #profiles = new Map();

  async loadProfile(profileId) {
    return clone(this.#profiles.get(profileId) ?? null);
  }

  async saveProfile(record) {
    requireRecord(record, "profile record");
    this.#profiles.set(record.profileId, clone(record));
  }

  async deleteProfile(profileId) {
    this.#profiles.delete(profileId);
  }

  async listProfiles() {
    return [...this.#profiles.values()].map(clone);
  }
}

export class FileBrowserStateStore {
  durable = true;
  #path;
  #directory;
  #profiles;

  constructor({ path }) {
    if (typeof path !== "string" || path.length === 0 || !isAbsolute(path)) {
      throw new TypeError("browser state store path must be absolute");
    }
    this.#path = resolve(path);
    this.#directory = dirname(this.#path);
    mkdirSync(this.#directory, { recursive: true, mode: 0o700 });
    if (realpathSync(this.#directory) !== this.#directory) {
      throw new TypeError("browser state store directory cannot traverse symlinks");
    }
    if (existsSync(this.#path)) {
      const metadata = lstatSync(this.#path);
      if (!metadata.isFile() || metadata.isSymbolicLink()) {
        throw new TypeError("browser state store must be a regular non-symlink file");
      }
      if (process.platform !== "win32" && (metadata.mode & 0o077) !== 0) {
        throw new TypeError("browser state store permissions are too broad");
      }
      const parsed = JSON.parse(readFileSync(this.#path, "utf8"));
      this.#profiles = validateEnvelope(parsed);
    } else {
      this.#profiles = new Map();
      this.#flush();
    }
  }

  async loadProfile(profileId) {
    return clone(this.#profiles.get(profileId) ?? null);
  }

  async saveProfile(record) {
    requireRecord(record, "profile record");
    this.#profiles.set(record.profileId, clone(record));
    this.#flush();
  }

  async deleteProfile(profileId) {
    if (this.#profiles.delete(profileId)) {
      this.#flush();
    }
  }

  async listProfiles() {
    return [...this.#profiles.values()].map(clone);
  }

  #flush() {
    const envelope = {
      schema: STORE_SCHEMA,
      profiles: [...this.#profiles.values()].sort((left, right) =>
        left.profileId.localeCompare(right.profileId),
      ),
    };
    const temporary = `${this.#path}.${process.pid}.${randomUUID()}.tmp`;
    const descriptor = openSync(temporary, "wx", 0o600);
    try {
      writeFileSync(descriptor, `${JSON.stringify(envelope)}\n`, "utf8");
      fsyncSync(descriptor);
    } finally {
      closeSync(descriptor);
    }
    try {
      renameSync(temporary, this.#path);
      if (process.platform !== "win32") {
        const directoryDescriptor = openSync(this.#directory, "r");
        try {
          fsyncSync(directoryDescriptor);
        } finally {
          closeSync(directoryDescriptor);
        }
      }
    } catch (error) {
      try {
        unlinkSync(temporary);
      } catch {
        // Best-effort temporary-file cleanup after a failed atomic replace.
      }
      throw error;
    }
  }
}
