/** Exact-integer TypeScript reference codec; not a permissive JSON.parse shim.
 * Run with Node 22 --experimental-strip-types. No third-party runtime dependencies.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

type Json = null | boolean | bigint | string | Json[] | { [key: string]: Json };
const profile = "canonical-json-utf8-sorted-keys-integer-only-preserve-unicode-v1";

class ExactJson {
  private cursor = 0;
  private readonly text: string;
  constructor(text: string) { this.text = text; }
  private space(): void { while (/[ \t\r\n]/.test(this.text[this.cursor] ?? "x")) this.cursor++; }
  private string(): string {
    const begin = this.cursor++;
    while (this.cursor < this.text.length) {
      const char = this.text[this.cursor++];
      if (char === "\\") this.cursor++;
      else if (char === '"') {
        const value = JSON.parse(this.text.slice(begin, this.cursor)) as string;
        // Reject lone UTF-16 surrogates instead of Buffer's silent replacement.
        if (!value.isWellFormed()) throw new Error("invalid Unicode scalar sequence");
        return value;
      }
    }
    throw new Error("unterminated string");
  }
  private value(depth: number): Json {
    if (depth > 64) throw new Error("JSON nesting limit");
    this.space();
    const char = this.text[this.cursor];
    if (char === '"') return this.string();
    if (char === "{") {
      this.cursor++;
      const result: { [key: string]: Json } = Object.create(null);
      this.space();
      if (this.text[this.cursor] === "}") { this.cursor++; return result; }
      for (;;) {
        this.space();
        if (this.text[this.cursor] !== '"') throw new Error("expected object key");
        const key = this.string();
        if (Object.hasOwn(result, key)) throw new Error("duplicate object key");
        this.space();
        if (this.text[this.cursor++] !== ":") throw new Error("expected colon");
        result[key] = this.value(depth + 1);
        this.space();
        const next = this.text[this.cursor++];
        if (next === "}") return result;
        if (next !== ",") throw new Error("expected object delimiter");
      }
    }
    if (char === "[") {
      this.cursor++;
      const result: Json[] = [];
      this.space();
      if (this.text[this.cursor] === "]") { this.cursor++; return result; }
      for (;;) {
        result.push(this.value(depth + 1));
        this.space();
        const next = this.text[this.cursor++];
        if (next === "]") return result;
        if (next !== ",") throw new Error("expected array delimiter");
      }
    }
    for (const [token, value] of [["null", null], ["true", true], ["false", false]] as const) {
      if (this.text.startsWith(token, this.cursor)) { this.cursor += token.length; return value; }
    }
    const match = /^-?(?:0|[1-9][0-9]*)/.exec(this.text.slice(this.cursor));
    if (!match) throw new Error("expected JSON integer");
    this.cursor += match[0].length;
    if (/[.eE0-9]/.test(this.text[this.cursor] ?? "x")) throw new Error("non-integer JSON number");
    const integer = BigInt(match[0]);
    if (integer < -(1n << 63n) || integer > (1n << 64n) - 1n) throw new Error("integer overflow");
    return integer;
  }
  parse(): Json {
    if (Buffer.byteLength(this.text) > 1_048_576) throw new Error("JSON byte limit");
    const result = this.value(0);
    this.space();
    if (this.cursor !== this.text.length) throw new Error("trailing JSON content");
    return result;
  }
}

function canonical(value: Json): string {
  if (typeof value === "bigint") return value.toString();
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const keys = Object.keys(value).sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
  return `{${keys.map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}
function component(value: Buffer): Buffer {
  const size = Buffer.alloc(8);
  size.writeBigUInt64BE(BigInt(value.length));
  return Buffer.concat([size, value]);
}
function hash(value: Buffer): string { return createHash("sha256").update(value).digest("hex"); }
function object(value: Json): { [key: string]: Json } {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("expected object");
  return value;
}
function string(value: Json): string {
  if (typeof value !== "string") throw new Error("expected string");
  return value;
}

const path = fileURLToPath(new URL("../../codex-rs/hepta-cognitive-types/tests/fixtures/closure_vectors.json", import.meta.url));
const raw = readFileSync(path);
const corpus = object(new ExactJson(new TextDecoder("utf-8", { fatal: true }).decode(raw)).parse());
if (corpus.canonicalizationAlgorithm !== profile || !Array.isArray(corpus.vectors)) throw new Error("corpus profile");
const names = new Set<string>();
const contracts = new Set<string>();
const results: { name: string; bound_digest: string }[] = [];
for (const value of corpus.vectors) {
  const row = object(value);
  const name = string(row.name), contract = string(row.contract), schema = string(row.schema);
  if (names.has(name)) throw new Error("duplicate vector name");
  names.add(name); contracts.add(contract);
  const payload = Buffer.from(canonical(row.payload));
  const legacy = hash(Buffer.concat([Buffer.from("hepta.cognitive.contract.canonical-json.v1\0"), Buffer.from(contract), Buffer.from([0]), payload]));
  const bound = hash(Buffer.concat([
    Buffer.from("hepta.cognitive.contract.bound-digest.v1\0"), component(Buffer.from(schema)),
    Buffer.from([0, 0, 0, 1]), component(Buffer.from(contract)), component(Buffer.from(profile)), component(payload),
  ]));
  if (legacy !== row.legacyDigest || bound !== row.boundDigest) throw new Error(`digest drift: ${name}`);
  results.push({ name, bound_digest: bound });
}
if (contracts.size !== 12 || !names.has("u64-maximum")) throw new Error("incomplete corpus");
for (const malformed of ['{"x":1,"x":2}', '1.5', '1e3', '01', '\u00a01', '18446744073709551616', '"\\ud800"']) {
  let rejected = false;
  try { new ExactJson(malformed).parse(); } catch { rejected = true; }
  if (!rejected) throw new Error(`parser accepted malformed input ${malformed}`);
}
console.log(JSON.stringify({ schema: "hepta.cognitive-types.corpus-result.v1", status: "passed", runtime: "typescript", vector_count: results.length, corpus_sha256: hash(raw), vectors: results }));
