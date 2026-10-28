import type { ChildProcess, SpawnOptions } from "node:child_process";

type Spawn = (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;
type Generation = {
  phase: "open" | "closing" | "closed";
  cancellation: AbortController;
  children: Map<ChildProcess, Promise<void>>;
  closed?: Promise<void>;
};

/** Admission and close barriers for explicitly registered, newly created fixture homes. */
export class OwnedCodexHomes {
  private readonly generations = new Map<string, Generation>();

  constructor(private readonly actualSpawn: Spawn) {}

  register(home: string): void {
    if (this.generations.has(home)) throw new Error("SDK fixture home was already registered");
    this.generations.set(home, {
      phase: "open",
      cancellation: new AbortController(),
      children: new Map(),
    });
  }

  spawn(
    command: string,
    args: readonly string[] | SpawnOptions = [],
    options?: SpawnOptions,
  ): ChildProcess {
    const argv = Array.isArray(args) ? args : [];
    const supplied = (Array.isArray(args) ? options : args) as SpawnOptions | undefined;
    const home = supplied?.env?.CODEX_HOME;
    const generation = typeof home === "string" ? this.generations.get(home) : undefined;
    if (!generation) return this.actualSpawn(command, argv, supplied ?? {});
    if (generation.phase !== "open") throw new Error("SDK fixture home is closing or closed");
    const signal = supplied?.signal
      ? AbortSignal.any([supplied.signal, generation.cancellation.signal])
      : generation.cancellation.signal;
    const child = this.actualSpawn(command, argv, { ...supplied, signal });
    generation.children.set(child, new Promise((resolve) => child.once("close", () => resolve())));
    return child;
  }

  close(home: string): Promise<void> {
    const generation = this.generations.get(home);
    if (!generation) return Promise.reject(new Error("SDK fixture home is not owned"));
    if (generation.closed) return generation.closed;
    // Close admission synchronously, before abort callbacks or child completion
    // can resume an old promise and attempt another process in this generation.
    generation.phase = "closing";
    let resolve!: () => void;
    let reject!: (reason: unknown) => void;
    generation.closed = new Promise<void>((done, failed) => {
      resolve = done;
      reject = failed;
    });
    void (async () => {
      generation.cancellation.abort(new Error("SDK fixture home is closing"));
      await Promise.all(
        [...generation.children].map(async ([child, closed]) => {
          if (child.exitCode === null && child.signalCode === null && !child.killed) child.kill();
          await closed;
        }),
      );
      generation.phase = "closed";
    })().then(resolve, reject);
    return generation.closed;
  }
}
