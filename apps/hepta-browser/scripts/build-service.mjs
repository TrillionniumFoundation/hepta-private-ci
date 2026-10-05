import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { mkdir, open, readFile, realpath, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { parse, version as parserVersion } from "acorn";
import { build, version } from "esbuild";

const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url));
const RECIPE = fileURLToPath(import.meta.url);
const BUILTINS = new Set([
  "node:child_process",
  "node:crypto",
  "node:fs",
  "node:fs/promises",
  "node:path",
]);
const MAX_SOURCE_BYTES = 1_048_576;
const MAX_CLOSURE_BYTES = 2_097_152;
const MAX_INPUTS = 64;
const MAX_SERVICE_BYTES = 8 * 1_048_576;
// A build-time guard for the reviewed static source graph, not a JavaScript
// sandbox or proof that arbitrary reflective code cannot execute new code.
const DYNAMIC_LOADERS = [
  "require",
  "createRequire",
  "getBuiltinModule",
  "eval",
  "Function",
];
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

function inspectModule(code, output = false) {
  const root = parse(code, { ecmaVersion: "latest", sourceType: "module" });
  const pending = [root];
  while (pending.length) {
    const node = pending.pop();
    if (!node || typeof node !== "object") continue;
    if (
      node.type === "ImportExpression" ||
      (node.type === "Identifier" && DYNAMIC_LOADERS.includes(node.name)) ||
      (node.type === "MemberExpression" &&
        node.property?.type === "Literal" &&
        DYNAMIC_LOADERS.includes(node.property.value)) ||
      ((node.type === "CallExpression" || node.type === "NewExpression") &&
        node.callee?.type === "Identifier" &&
        ["require", "createRequire", "eval", "Function"].includes(
          node.callee.name,
        ))
    ) {
      throw new TypeError("Browser service build requires static ESM imports");
    }
    if (
      output &&
      node.source &&
      [
        "ImportDeclaration",
        "ExportNamedDeclaration",
        "ExportAllDeclaration",
      ].includes(node.type) &&
      !BUILTINS.has(node.source.value)
    ) {
      throw new TypeError("Browser service output contains an unbound import");
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) pending.push(...value);
      else if (value && typeof value === "object") pending.push(value);
    }
  }
}

async function sourceBytes(path) {
  const handle = await open(
    path,
    constants.O_RDONLY |
      (constants.O_NOFOLLOW ?? 0) |
      (constants.O_NONBLOCK ?? 0),
  );
  try {
    const before = await handle.stat({ bigint: true });
    if (
      !before.isFile() ||
      before.size < 1n ||
      before.size > BigInt(MAX_SOURCE_BYTES)
    ) {
      throw new TypeError(
        "Browser service input must be a bounded regular file",
      );
    }
    const buffer = Buffer.alloc(Number(before.size) + 1);
    let count = 0;
    while (count < buffer.length) {
      const result = await handle.read(
        buffer,
        count,
        buffer.length - count,
        null,
      );
      if (!result.bytesRead) break;
      count += result.bytesRead;
    }
    const after = await handle.stat({ bigint: true });
    if (
      count !== Number(before.size) ||
      after.size !== before.size ||
      after.mtimeNs !== before.mtimeNs ||
      after.ctimeNs !== before.ctimeNs
    ) {
      throw new TypeError("Browser service input changed while building");
    }
    return buffer.subarray(0, count);
  } finally {
    await handle.close();
  }
}

export async function buildService({
  outputPath,
  sourceRoot = resolve(PACKAGE_ROOT, "src"),
}) {
  if (version !== "0.28.1" || parserVersion !== "8.15.0") {
    throw new TypeError(
      "Browser service builder versions differ from the reviewed recipe",
    );
  }
  const root = await realpath(sourceRoot);
  const workingDirectory = dirname(root);
  const inputs = new Map();
  let totalBytes = 0;
  const result = await build({
    absWorkingDir: workingDirectory,
    entryPoints: [resolve(root, "agentd-service-main.js")],
    outfile: "browser-service.mjs",
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node24",
    splitting: false,
    sourcemap: false,
    write: false,
    metafile: true,
    legalComments: "none",
    logLevel: "silent",
    plugins: [
      {
        name: "browser-service-closure",
        setup(builder) {
          builder.onResolve({ filter: /.*/ }, async (args) => {
            if (BUILTINS.has(args.path))
              return { path: args.path, external: true };
            if (
              args.kind !== "entry-point" &&
              !args.path.startsWith("./") &&
              !args.path.startsWith("../")
            ) {
              throw new TypeError(
                `Unreviewed Browser service dependency: ${args.path}`,
              );
            }
            const path = resolve(
              args.resolveDir || workingDirectory,
              args.path,
            );
            const selected = await realpath(path);
            if (
              !selected.startsWith(root + sep) ||
              selected !== path ||
              !path.endsWith(".js")
            ) {
              throw new TypeError(
                "Browser service input escapes its reviewed source directory",
              );
            }
            return { path };
          });
          builder.onLoad({ filter: /\.js$/ }, async ({ path }) => {
            let input = inputs.get(path);
            if (!input) {
              const bytes = await sourceBytes(path);
              totalBytes += bytes.length;
              if (inputs.size >= MAX_INPUTS || totalBytes > MAX_CLOSURE_BYTES) {
                throw new TypeError(
                  "Browser service closure exceeds its build bounds",
                );
              }
              const code = new TextDecoder("utf-8", { fatal: true }).decode(
                bytes,
              );
              inspectModule(code);
              input = {
                code,
                path: relative(workingDirectory, path).split(sep).join("/"),
                sha256: sha256(bytes),
              };
              inputs.set(path, input);
            }
            return {
              contents: input.code,
              loader: "js",
              resolveDir: dirname(path),
            };
          });
        },
      },
    ],
  });
  if (result.warnings.length || result.outputFiles.length !== 1) {
    throw new TypeError(
      "Browser service build must produce one warning-free artifact",
    );
  }
  const bytes = result.outputFiles[0].contents;
  if (!bytes.length || bytes.length > MAX_SERVICE_BYTES)
    throw new TypeError("Browser service output exceeds bounds");
  inspectModule(new TextDecoder("utf-8", { fatal: true }).decode(bytes), true);
  const outputs = Object.values(result.metafile.outputs);
  const externalModules = [
    ...new Set(
      outputs.flatMap((output) =>
        output.imports.map((item) => {
          if (!item.external || !BUILTINS.has(item.path))
            throw new TypeError(
              "Browser service output has an unbound dependency",
            );
          return item.path;
        }),
      ),
    ),
  ].sort();
  const receipt = {
    schema: "hepta.browser.service-build-receipt.v1",
    builder: { name: "esbuild", version, parserVersion },
    nodeTarget: "node24",
    bundleSha256: sha256(bytes),
    inputs: [...inputs.values()]
      .map(({ path, sha256 }) => ({ path, sha256 }))
      .sort((a, b) => Buffer.compare(Buffer.from(a.path), Buffer.from(b.path))),
    externalModules,
    buildRecipeSha256: sha256(await readFile(RECIPE)),
    packageLockSha256: sha256(
      await readFile(resolve(PACKAGE_ROOT, "package-lock.json")),
    ),
  };
  await mkdir(dirname(resolve(outputPath)), { recursive: true });
  await writeFile(outputPath, bytes, { flag: "wx", mode: 0o400 });
  await writeFile(
    `${outputPath}.receipt.json`,
    JSON.stringify(receipt) + "\n",
    { flag: "wx", mode: 0o400 },
  );
  return receipt;
}

if (process.argv[1] && resolve(process.argv[1]) === RECIPE) {
  if (process.argv.length !== 3 || !isAbsolute(process.argv[2])) {
    throw new TypeError(
      "Usage: node build-service.mjs /absolute/path/service.mjs",
    );
  }
  await buildService({ outputPath: process.argv[2] });
}
