import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";

const packageRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const dist = resolve(packageRoot, "dist");
const port = Number(process.env.PORT ?? 4173);

if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
  throw new TypeError("PORT must be a valid TCP port");
}

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
]);

const headers = {
  "Cache-Control": "no-store",
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
};

createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const requestPath = url.pathname === "/" ? "/web/index.html" : url.pathname;
    const normalized = requestPath.replace(/^\/+/, "");
    const path = resolve(dist, normalized);
    if (path !== dist && !path.startsWith(`${dist}/`)) {
      response.writeHead(404, headers);
      response.end("Not found\n");
      return;
    }
    const info = await stat(path);
    if (!info.isFile()) {
      throw new Error("not a file");
    }
    response.writeHead(200, {
      ...headers,
      "Content-Type": contentTypes.get(extname(path)) ?? "application/octet-stream",
    });
    createReadStream(path).pipe(response);
  } catch {
    response.writeHead(404, headers);
    response.end("Not found\n");
  }
}).listen(port, "127.0.0.1", () => {
  console.log(`ui.control development server listening on http://127.0.0.1:${port}`);
});
