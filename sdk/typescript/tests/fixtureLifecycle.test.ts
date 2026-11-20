import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs/promises";
import { createInterface } from "node:readline";

import os from "node:os";
import path from "node:path";

import { expect, it, jest } from "@jest/globals";

import { OwnedCodexHomes } from "./ownedCodexHomes";

import { closeCurrentCodexHome } from "./setupCodexHome";

it("rejects an old-home continuation before it can spawn while fixture close is joining", async () => {
  const home = process.env.CODEX_HOME!;
  const env = { ...process.env, CODEX_HOME: home };
  const first = spawn(
    process.execPath,
    [
      "-e",
      'process.on("SIGTERM", () => setTimeout(() => process.exit(0), 80)); process.stdout.write("ready\\n"); setInterval(() => {}, 1000);',
    ],
    { env },
  );
  first.on("error", () => {
    /* Fixture cancellation emits the expected AbortError. */
  });
  let second: ChildProcess | undefined;
  let rejected: unknown;
  const ready = createInterface({ input: first.stdout! });
  await new Promise<void>((resolve) => ready.once("line", () => resolve()));
  ready.close();
  const continued = new Promise<void>((resolve) => {
    first.once("close", () => {
      try {
        second = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { env });
      } catch (error) {
        rejected = error;
      }
      resolve();
    });
  });
  try {
    await closeCurrentCodexHome();
    await continued;
    expect(second).toBeUndefined();
    expect(rejected).toBeInstanceOf(Error);
    await expect(fs.stat(home)).rejects.toMatchObject({ code: "ENOENT" });
  } finally {
    for (const child of [first, second]) {
      if (child && child.exitCode === null && child.signalCode === null) {
        const closed = new Promise<void>((resolve) => child.once("close", () => resolve()));
        child.kill("SIGKILL");
        await closed;
      }
    }
  }
});

it("keeps a closed generation fenced while another owned home remains usable", async () => {
  const actual = jest.requireActual<typeof import("node:child_process")>("node:child_process");
  const homes = new OwnedCodexHomes(actual.spawn);
  const firstHome = await fs.mkdtemp(path.join(os.tmpdir(), "codex-sdk-generation-"));
  const secondHome = await fs.mkdtemp(path.join(os.tmpdir(), "codex-sdk-generation-"));
  homes.register(firstHome);
  homes.register(secondHome);
  const children: ChildProcess[] = [];
  const launch = async (home: string) => {
    const child = homes.spawn(
      process.execPath,
      [
        "-e",
        'process.stdin.on("data", () => process.stdout.write("alive\\n")); process.stdout.write("ready\\n");',
      ],
      {
        env: { ...process.env, CODEX_HOME: home },
      },
    );
    children.push(child);
    child.on("error", () => {
      /* Fixture cancellation emits the expected AbortError. */
    });
    const lines = createInterface({ input: child.stdout! });
    await new Promise<void>((resolve) => lines.once("line", () => resolve()));
    return { child, lines };
  };
  try {
    const first = await launch(firstHome);
    const second = await launch(secondHome);
    const closing = homes.close(firstHome);
    expect(homes.close(firstHome)).toBe(closing);
    await closing;
    first.lines.close();
    await fs.rm(firstHome, { recursive: true });
    expect(() =>
      homes.spawn(process.execPath, { env: { ...process.env, CODEX_HOME: firstHome } }),
    ).toThrow("closing or closed");
    expect(() => homes.register(firstHome)).toThrow("already registered");
    const alive = new Promise<string>((resolve) => second.lines.once("line", resolve));
    second.child.stdin!.write("ping");
    expect(await alive).toBe("alive");
    expect(second.child.exitCode).toBeNull();
    expect(second.child.killed).toBe(false);
    await homes.close(secondHome);
    second.lines.close();
  } finally {
    for (const child of children) {
      if (child.exitCode === null && child.signalCode === null) {
        const closed = new Promise<void>((resolve) => child.once("close", () => resolve()));
        child.kill("SIGKILL");
        await closed;
      }
    }
    await fs.rm(firstHome, { recursive: true, force: true });
    await fs.rm(secondHome, { recursive: true, force: true });
  }
});
