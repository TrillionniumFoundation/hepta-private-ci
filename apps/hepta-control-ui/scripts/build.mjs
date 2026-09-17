import { copyFile, mkdir, readdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "src");
const destination = join(root, "dist");
await rm(destination, { recursive: true, force: true });
await mkdir(destination, { recursive: true });
for (const entry of await readdir(source, { withFileTypes: true })) {
  if (entry.isFile() && entry.name.endsWith(".js")) {
    await copyFile(join(source, entry.name), join(destination, entry.name));
  }
}
