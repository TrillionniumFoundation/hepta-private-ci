import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, extname, join, parse } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const sourceDir = join(root, "src");
const webDir = join(root, "web");
const destination = join(root, "dist");
const assetsDir = join(destination, "assets");

function digest(buffer) {
  const hash = createHash("sha256").update(buffer).digest();
  return {
    hex: hash.toString("hex"),
    short: hash.toString("hex").slice(0, 12),
    integrity: `sha256-${hash.toString("base64")}`,
  };
}

await rm(destination, { recursive: true, force: true });
await mkdir(assetsDir, { recursive: true });

const sourceFiles = (await readdir(sourceDir, { withFileTypes: true }))
  .filter((entry) => entry.isFile() && entry.name.endsWith(".js"))
  .map((entry) => entry.name)
  .sort();
const sourceSet = new Set(sourceFiles);
const originals = new Map();
for (const file of sourceFiles) {
  originals.set(file, await readFile(join(sourceDir, file), "utf8"));
}

const outputNames = new Map();
const manifestAssets = [];
const visiting = new Set();

async function buildModule(file) {
  if (outputNames.has(file)) return outputNames.get(file);
  if (!sourceSet.has(file)) throw new Error(`missing source module ${file}`);
  if (visiting.has(file)) throw new Error(`cyclic browser module graph at ${file}`);
  visiting.add(file);

  let content = originals.get(file);
  const dependencies = [
    ...content.matchAll(/(?:from\s+|import\s*)["']\.\/(.+?\.js)["']/g),
  ].map((match) => match[1]);
  for (const dependency of dependencies) {
    const output = await buildModule(dependency);
    content = content.replaceAll(`"./${dependency}"`, `"./${output}"`);
    content = content.replaceAll(`'./${dependency}'`, `'./${output}'`);
  }

  const bytes = Buffer.from(content);
  const info = digest(bytes);
  const output = `${parse(file).name}.${info.short}.js`;
  outputNames.set(file, output);
  await writeFile(join(assetsDir, output), bytes);
  manifestAssets.push({
    source: `src/${file}`,
    path: `assets/${output}`,
    bytes: bytes.byteLength,
    sha256: info.hex,
    integrity: info.integrity,
    mediaType: "text/javascript",
  });
  visiting.delete(file);
  return output;
}

for (const file of sourceFiles) await buildModule(file);
const cssSource = await readFile(join(webDir, "styles.css"));
const cssInfo = digest(cssSource);
const cssName = `styles.${cssInfo.short}.css`;
await writeFile(join(assetsDir, cssName), cssSource);
manifestAssets.push({
  source: "web/styles.css",
  path: `assets/${cssName}`,
  bytes: cssSource.byteLength,
  sha256: cssInfo.hex,
  integrity: cssInfo.integrity,
  mediaType: "text/css",
});

const entryName = outputNames.get("web-main.js");
const entry = manifestAssets.find((asset) => asset.path === `assets/${entryName}`);
if (!entry) throw new Error("web-main.js entry asset was not produced");

const csp = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "connect-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");
const index = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <title>Hepta control plane</title>
  <link rel="stylesheet" href="./assets/${cssName}" integrity="${cssInfo.integrity}" crossorigin="anonymous">
</head>
<body>
  <div id="app"><p role="status">Connecting to authenticated runtime…</p></div>
  <noscript>This control plane requires JavaScript.</noscript>
  <script type="module" src="./assets/${entryName}" integrity="${entry.integrity}" crossorigin="anonymous"></script>
</body>
</html>
`;
await writeFile(join(destination, "index.html"), index);

const buildManifest = {
  schema: "hepta.ui-control.web-build.v1",
  entry: `assets/${entryName}`,
  stylesheet: `assets/${cssName}`,
  assets: manifestAssets,
  securityHeaders: {
    "Content-Security-Policy": `${csp}; frame-ancestors 'none'`,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
  },
};
await writeFile(join(destination, "asset-manifest.json"), `${JSON.stringify(buildManifest, null, 2)}\n`);
await writeFile(
  join(destination, "manifest.webmanifest"),
  `${JSON.stringify({
    name: "Hepta control plane",
    short_name: "Hepta Control",
    start_url: "./",
    display: "standalone",
    scope: "./",
  }, null, 2)}\n`,
);
await writeFile(
  join(destination, "security-headers.json"),
  `${JSON.stringify(buildManifest.securityHeaders, null, 2)}\n`,
);

for (const asset of manifestAssets.filter((item) => item.mediaType === "text/javascript")) {
  const content = await readFile(join(destination, asset.path), "utf8");
  const imports = [...content.matchAll(/(?:from\s+|import\s*)["']\.\/(.+?\.js)["']/g)].map((match) => match[1]);
  for (const imported of imports) {
    if (!manifestAssets.some((candidate) => candidate.path === `assets/${imported}`)) {
      throw new Error(`${asset.path} imports missing build asset ${imported}`);
    }
  }
}
