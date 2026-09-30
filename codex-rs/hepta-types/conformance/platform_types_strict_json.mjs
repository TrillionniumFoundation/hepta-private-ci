// Shared bounded strict-JSON admission for independent protocol oracles.
export const MAX_RAW_BYTES = 65536;
const MAX_RAW_DEPTH = 16;
const TOKENS = /"(?:\\.|[^"\\])*"|(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/g;

function maxDepth(raw) {
  let depth = 0; let maximum = 0; let quoted = false; let escaped = false;
  for (const character of raw) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
    } else if (character === '"') quoted = true;
    else if (character === "[" || character === "{") { depth += 1; maximum = Math.max(maximum, depth); }
    else if (character === "]" || character === "}") depth -= 1;
  }
  return maximum;
}

export function parseStrictJson(raw) {
  if (typeof raw !== "string" || raw.length > MAX_RAW_BYTES || Buffer.byteLength(raw) > MAX_RAW_BYTES) throw new Error("size_exceeded");
  if (maxDepth(raw) > MAX_RAW_DEPTH) throw new Error("depth_exceeded");
  const value = JSON.parse(raw);
  // JSON.parse validates the bounded syntax; retain each object's decoded keys
  // separately because it otherwise silently overwrites each duplicate key.
  const scopes = [];
  for (let index = 0; index < raw.length; index += 1) {
    const character = raw[index];
    if (character === "{") scopes.push(new Set());
    else if (character === "[") scopes.push(null);
    else if (character === "}" || character === "]") scopes.pop();
    else if (character === '"') {
      const start = index;
      for (index += 1; index < raw.length; index += 1) {
        if (raw[index] === "\\") index += 1;
        else if (raw[index] === '"') break;
      }
      let next = index + 1;
      while (next < raw.length && /[\t\n\r ]/.test(raw[next])) next += 1;
      if (raw[next] === ":") {
        const key = JSON.parse(raw.slice(start, index + 1));
        const keys = scopes.at(-1);
        if (keys.has(key)) throw new Error("duplicate_key");
        keys.add(key);
      }
    }
  }
  return value;
}

export function assertUnsignedIntegerTokens(raw) {
  // Call after strict JSON syntax admission. Product numeric fields are u32;
  // number lexemes must retain integer spelling instead of JSON.parse coercion.
  for (const match of raw.matchAll(TOKENS)) {
    if (match[1] !== undefined && !/^(?:0|[1-9][0-9]*)$/.test(match[1])) {
      throw new Error("unsigned_integer_token");
    }
  }
}
