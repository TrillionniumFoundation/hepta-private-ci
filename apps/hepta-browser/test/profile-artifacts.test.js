import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, chmod } from "node:fs/promises";
import net from "node:net";
import { join } from "node:path";
import test from "node:test";
import { browserProfileArtifactPaths, MAX_BROWSER_SOCKET_PATH_BYTES } from "../src/profile-artifacts.js";

test("short private artifact paths support an actual Unix listener", async t => {
  const root = await mkdtemp("/tmp/hepta-path-");
  t.after(() => rm(root, { recursive: true, force: true }));
  await chmod(root, 0o700);
  const paths = browserProfileArtifactPaths(root);
  await mkdir(paths.profileDir, { mode: 0o700 });
  const server = net.createServer(socket => socket.end("ok"));
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(paths.socketPath, resolve);
  });
  t.after(() => new Promise(resolve => server.close(resolve)));
  const value = await new Promise((resolve, reject) => {
    const socket = net.createConnection(paths.socketPath);
    const chunks = [];
    socket.on("data", chunk => chunks.push(chunk));
    socket.on("end", () => resolve(Buffer.concat(chunks).toString()));
    socket.on("error", reject);
  });
  assert.equal(value, "ok");
  assert.ok(Buffer.byteLength(paths.socketPath) <= MAX_BROWSER_SOCKET_PATH_BYTES);
  assert.equal(paths.socketPath, join(paths.profileDir, ".hepta-egress.sock"));
});

test("allocation is random and does not derive OS names from user identifiers", () => {
  const values = new Set(Array.from({ length: 1024 }, () => browserProfileArtifactPaths("/tmp/private").profileDir));
  assert.equal(values.size, 1024);
  for (const value of values) assert.match(value, /\/p\.[0-9a-f]{32}$/);
});

test("overlong, multibyte, relative and NUL roots reject without truncation", () => {
  for (const path of ["relative", "/tmp/\0x", "/tmp/" + "x".repeat(70), "/tmp/" + "界".repeat(25)]) {
    assert.throws(() => browserProfileArtifactPaths(path), TypeError);
  }
});
