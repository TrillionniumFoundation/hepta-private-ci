import * as childProcess from "node:child_process";

import { expect, it } from "@jest/globals";

jest.mock("node:child_process", () => {
  const actual = jest.requireActual<typeof import("node:child_process")>("node:child_process");
  return { ...actual, spawn: jest.fn() };
});

const actual = jest.requireActual<typeof import("node:child_process")>("node:child_process");
const spawnMock = childProcess.spawn as jest.MockedFunction<typeof actual.spawn>;

it("joins a real child with delayed termination before an early consumer return resolves", async () => {
  const { CodexExec } = await import("../src/exec");
  let closed = false;
  let child: childProcess.ChildProcess | undefined;
  spawnMock.mockImplementation((_executable, _args, options) => {
    child = actual.spawn(
      process.execPath,
      [
        "-e",
        'process.on("SIGTERM", () => setTimeout(() => process.exit(0), 80)); process.stdout.write("ready\\n"); setInterval(() => {}, 1000);',
      ],
      options,
    );
    const emit = child.emit;
    child.emit = function (event: string | symbol, ...args: unknown[]) {
      if (event === "close") closed = true;
      return Reflect.apply(emit, this, [event, ...args]) as boolean;
    };
    return child;
  });
  try {
    for await (const line of new CodexExec("test-owned-child").run({ input: "fixture" })) {
      expect(line).toBe("ready");
      break;
    }
    expect(closed).toBe(true);
  } finally {
    if (child && !closed) {
      const close = new Promise<void>((resolve) => child!.once("close", () => resolve()));
      child.kill("SIGKILL");
      await close;
    }
  }
});
