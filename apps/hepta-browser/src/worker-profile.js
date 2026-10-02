import { lstat, mkdir, realpath } from "node:fs/promises";
import { join, parse, resolve, sep } from "node:path";

// A verified executable remains bound to its bytes only while every path
// component above its private copy prevents replacement by another user.
export async function ensurePrivateWorkerProfileRoot(path) {
  const canonical = resolve(path);
  const root = parse(canonical).root;
  const components = canonical.slice(root.length).split(sep).filter(Boolean);
  let current = root;
  for (const component of [null, ...components]) {
    if (component !== null) current = join(current, component);
    let info;
    try {
      info = await lstat(current);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      try {
        await mkdir(current, { mode: 0o700 });
      } catch (creationError) {
        if (creationError?.code !== "EEXIST") throw creationError;
      }
      info = await lstat(current);
    }
    if (!info.isDirectory() || info.isSymbolicLink()) {
      throw new TypeError(
        "browser worker profile path contains a symlink or non-directory",
      );
    }
    if (process.platform !== "win32") {
      const owned = info.uid === process.getuid();
      const trustedOwner = owned || info.uid === 0;
      const unsafeWritable =
        (info.mode & 0o022) !== 0 && (info.mode & 0o1000) === 0;
      if (
        current === canonical
          ? !owned || (info.mode & 0o077) !== 0
          : !trustedOwner || unsafeWritable
      ) {
        throw new TypeError(
          "browser worker profile path permissions or owner are unsafe",
        );
      }
    }
  }
  if ((await realpath(canonical)) !== canonical) {
    throw new TypeError("browser worker profile path is not canonical");
  }
  return canonical;
}
