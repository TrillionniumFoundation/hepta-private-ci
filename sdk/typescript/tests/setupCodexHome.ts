import fs from "node:fs/promises";
import type { SpawnOptions } from "node:child_process";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, jest } from "@jest/globals";

import { OwnedCodexHomes } from "./ownedCodexHomes";

const originalCodexHome = process.env.CODEX_HOME;
let currentCodexHome: string | undefined;
const actualChildProcess =
  jest.requireActual<typeof import("node:child_process")>("node:child_process");
const mockOwnedHomes = new OwnedCodexHomes(actualChildProcess.spawn);

// Keep the admission capability attached to the SDK's imported module for the
// generation's whole lifetime, including old continuations after another test.
jest.mock("node:child_process", () => {
  const actual = jest.requireActual<typeof import("node:child_process")>("node:child_process");
  return {
    ...actual,
    spawn: jest.fn(
      (command: string, args?: readonly string[] | SpawnOptions, options?: SpawnOptions) =>
        mockOwnedHomes.spawn(command, args, options),
    ),
  };
});

beforeEach(async () => {
  currentCodexHome = await fs.mkdtemp(path.join(os.tmpdir(), "codex-sdk-test-"));
  mockOwnedHomes.register(currentCodexHome);
  process.env.CODEX_HOME = currentCodexHome;
});

export async function closeCurrentCodexHome() {
  const codexHomeToDelete = currentCodexHome;
  try {
    if (codexHomeToDelete) {
      await mockOwnedHomes.close(codexHomeToDelete);
      await fs.rm(codexHomeToDelete, { recursive: true, force: true });
    }
  } finally {
    currentCodexHome = undefined;
    if (originalCodexHome === undefined) delete process.env.CODEX_HOME;
    else process.env.CODEX_HOME = originalCodexHome;
  }
}

afterEach(closeCurrentCodexHome);
