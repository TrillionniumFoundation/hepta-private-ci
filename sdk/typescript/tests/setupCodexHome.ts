import fs from "node:fs/promises";
import type { ChildProcess } from "node:child_process";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, jest } from "@jest/globals";

const originalCodexHome = process.env.CODEX_HOME;
let currentCodexHome: string | undefined;
const childProcess = jest.requireActual<typeof import("node:child_process")>("node:child_process");
const originalSpawn = childProcess.spawn;
const ownedChildren = new Map<ChildProcess, Promise<void>>();
let spawnSpy: jest.SpiedFunction<typeof childProcess.spawn> | undefined;

beforeEach(async () => {
  currentCodexHome = await fs.mkdtemp(path.join(os.tmpdir(), "codex-sdk-test-"));
  process.env.CODEX_HOME = currentCodexHome;
  spawnSpy = jest.spyOn(childProcess, "spawn").mockImplementation((command, args, options) => {
    const child = originalSpawn(command, args, options);
    if (options?.env?.CODEX_HOME === currentCodexHome) {
      ownedChildren.set(child, new Promise((resolve) => child.once("close", () => resolve())));
    }
    return child;
  });
});

afterEach(async () => {
  const codexHomeToDelete = currentCodexHome;
  try {
    // A Jest timeout does not cancel the promise under test. Stop only children
    // spawned with this fixture's home and join their stdio before deleting it.
    await Promise.all(
      [...ownedChildren].map(async ([child, closed]) => {
        if (child.exitCode === null && child.signalCode === null && !child.killed) child.kill();
        await closed;
      }),
    );
    if (codexHomeToDelete) await fs.rm(codexHomeToDelete, { recursive: true, force: true });
  } finally {
    ownedChildren.clear();
    spawnSpy?.mockRestore();
    currentCodexHome = undefined;
    if (originalCodexHome === undefined) delete process.env.CODEX_HOME;
    else process.env.CODEX_HOME = originalCodexHome;
  }
});
