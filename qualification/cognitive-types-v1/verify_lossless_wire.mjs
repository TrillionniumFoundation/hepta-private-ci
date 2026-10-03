// Independent lossless-integer canonical encoding/digest oracle, not an owner.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const input = readFileSync(0);
if (input.length > 1049600) throw new Error('wire length exceeds bound');
const text = new TextDecoder('utf-8', { fatal: true }).decode(input);
let index = 0;
function scalarString(value) {
  for (const scalar of value) {
    const code = scalar.codePointAt(0);
    if (code >= 0xd800 && code <= 0xdfff) throw new Error('unpaired surrogate');
  }
  return value;
}
function string() {
  const start = index++;
  while (index < text.length) {
    const character = text[index++];
    if (character === '\\') index++;
    else if (character === '"') return scalarString(JSON.parse(text.slice(start, index)));
  }
  throw new Error('unterminated string');
}
function value(depth = 0) {
  if (depth > 64) throw new Error('maximum nesting exceeded');
  if (text[index] === '"') return string();
  if (text[index] === '[') {
    index++;
    const result = [];
    if (text[index] === ']') { index++; return result; }
    while (true) {
      result.push(value(depth + 1));
      const delimiter = text[index++];
      if (delimiter === ']') return result;
      if (delimiter !== ',') throw new Error('array delimiter');
    }
  }
  if (text[index] === '{') {
    index++;
    const result = Object.create(null);
    if (text[index] === '}') { index++; return result; }
    while (true) {
      if (text[index] !== '"') throw new Error('object key');
      const key = string();
      if (Object.hasOwn(result, key)) throw new Error('duplicate key');
      if (text[index++] !== ':') throw new Error('object colon');
      result[key] = value(depth + 1);
      const delimiter = text[index++];
      if (delimiter === '}') return result;
      if (delimiter !== ',') throw new Error('object delimiter');
    }
  }
  for (const [token, result] of [['true', true], ['false', false], ['null', null]]) {
    if (text.startsWith(token, index)) { index += token.length; return result; }
  }
  const integer = /^-?(?:0|[1-9][0-9]*)/.exec(text.slice(index));
  if (!integer) throw new Error('integer or value required');
  index += integer[0].length;
  const result = BigInt(integer[0]);
  if (result < -(1n << 63n) || result > (1n << 64n) - 1n) throw new Error('integer range');
  return result;
}
function canonical(item) {
  if (item === null) return 'null';
  if (typeof item === 'bigint') return item.toString();
  if (typeof item === 'string' || typeof item === 'boolean') return JSON.stringify(item);
  if (Array.isArray(item)) return '[' + item.map(canonical).join(',') + ']';
  if (typeof item !== 'object') throw new Error('unsupported value');
  const keys = Object.keys(item).sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
  return '{' + keys.map(key => JSON.stringify(key) + ':' + canonical(item[key])).join(',') + '}';
}
function framed(part) {
  const bytes = Buffer.from(part);
  const length = Buffer.alloc(8);
  length.writeBigUInt64BE(BigInt(bytes.length));
  return Buffer.concat([length, bytes]);
}
function hash(...parts) {
  const digest = createHash('sha256');
  for (const part of parts) digest.update(part);
  return digest.digest('hex');
}
try {
  const envelope = value();
  if (index !== text.length || canonical(envelope) !== text) throw new Error('noncanonical input');
  if (envelope.schemaVersion !== 1n || typeof envelope.schema !== 'string' || typeof envelope.contract !== 'string') {
    throw new Error('invalid envelope metadata');
  }
  const payload = canonical(envelope.payload);
  const version = Buffer.alloc(4);
  version.writeUInt32BE(1);
  const algorithm = 'canonical-json-utf8-sorted-keys-integer-only-preserve-unicode-v1';
  console.log(JSON.stringify({
    outcome: 'accepted', contract: envelope.contract, encoded_bytes: input.length,
    wire_sha256: hash(input),
    frozen_sha256: hash('hepta.cognitive.contract.canonical-json.v1\0', envelope.contract, '\0', payload),
    bound_sha256: hash('hepta.cognitive.contract.bound-digest.v1\0', framed(envelope.schema), version,
                       framed(envelope.contract), framed(algorithm), framed(payload)),
  }));
} catch (error) {
  console.log(JSON.stringify({ outcome: 'rejected', error: String(error) }));
  process.exitCode = 2;
}
