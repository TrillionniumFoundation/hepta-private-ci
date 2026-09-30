import { spawn } from "node:child_process";
import { constants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";

const LOCK_HEADER = "hepta.browser.kernel-owner-lock.v2\n";
const FLOCK_PATH = "/usr/bin/flock";

export class BrowserJournalLockedError extends Error {}

function privateRegular(info, label) {
  if (!info.isFile() || info.nlink !== 1 || (info.mode & 0o077) !== 0 ||
      info.uid !== process.geteuid()) {
    throw new TypeError(`${label} must be a private, singly-linked owner file`);
  }
}

// flock(2) belongs to the inherited open-file description, not the utility's
// PID. After /usr/bin/flock exits, the parent retains FD 3's description until
// release. SIGKILL of the owner closes it in the kernel: no PID/stale deletion.
// The permanent lock inode must NEVER be unlinked by a live process. This is an
// advisory local-Linux-filesystem protocol; mixed old/new writers are forbidden.
export async function acquireBrowserJournalLock(journalPath, timeoutMs = 5000) {
  if (process.platform !== "linux") {
    throw new TypeError("Browser journal kernel ownership requires Linux");
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000) {
    throw new TypeError("journal owner lock timeout is outside its hard bound");
  }
  const executable = await lstat(FLOCK_PATH);
  if (!executable.isFile() || executable.isSymbolicLink() || executable.uid !== 0 ||
      (executable.mode & 0o022) !== 0 || await realpath(FLOCK_PATH) !== FLOCK_PATH) {
    throw new TypeError("journal flock launcher is not a protected host executable");
  }
  const path = `${journalPath}.owner-lock`;
  let handle;
  try {
    handle = await open(path, constants.O_RDWR | constants.O_CREAT |
      constants.O_NOFOLLOW, 0o600);
    const before = await handle.stat();
    privateRegular(before, "journal owner lock");
    if (before.size > 4096) throw new TypeError("journal owner lock metadata is oversized");
    const prior = await handle.readFile("utf8");
    if (prior !== "" && prior !== LOCK_HEADER) {
      throw new TypeError("legacy journal owner lock requires offline migration with all writers stopped");
    }
    await new Promise((resolve, reject) => {
      const child = spawn(FLOCK_PATH, ["--exclusive", "--timeout", String(timeoutMs / 1000), "3"], {
        env: {}, stdio: ["ignore", "ignore", "ignore", handle.fd],
      });
      let timedOut = false;
      const timer = setTimeout(() => { timedOut = true; child.kill("SIGKILL"); }, timeoutMs + 1000);
      child.once("error", error => { clearTimeout(timer); reject(error); });
      child.once("exit", (code, signal) => {
        clearTimeout(timer);
        if (code === 0 && !timedOut) resolve();
        else if (code === 1 || timedOut) reject(new BrowserJournalLockedError("browser journal owner lock deadline exceeded"));
        else reject(new Error(`journal flock failed: code=${code}, signal=${signal}`));
      });
    });
    const current = await lstat(path);
    privateRegular(current, "journal owner lock");
    if (current.dev !== before.dev || current.ino !== before.ino) {
      throw new Error("journal lock inode changed during acquisition");
    }
    if (current.size === 0) {
      await handle.write(LOCK_HEADER, 0, "utf8");
      await handle.sync();
    } else {
      const body = Buffer.alloc(current.size);
      await handle.read(body, 0, body.length, 0);
      if (body.toString("utf8") !== LOCK_HEADER) throw new Error("journal owner lock protocol changed");
    }
    let released = false;
    const locked = handle;
    handle = null;
    return async () => {
      if (released) return;
      released = true;
      try {
        const final = await lstat(path);
        if (final.dev !== before.dev || final.ino !== before.ino) {
          throw new Error("journal lock inode was replaced while owned");
        }
      } finally {
        await locked.close();
      }
    };
  } catch (error) {
    await handle?.close().catch(() => {});
    if (error?.code === "EISDIR") {
      throw new TypeError("legacy journal owner directory requires offline migration with all writers stopped");
    }
    throw error;
  }
}
