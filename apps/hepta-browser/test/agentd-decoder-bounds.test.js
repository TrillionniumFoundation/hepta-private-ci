import assert from "node:assert/strict";
import test from "node:test";
import {
  AgentdBrowserFrameDecoder,
  buildAgentdBrowserFrame,
  encodeAgentdBrowserFrame,
  MAX_BROWSER_AGENTD_FRAME_BYTES,
} from "../src/agentd-protocol.js";

function frame(sequence = 1, payload = { text: "日本語" }) {
  return buildAgentdBrowserFrame({ sequence, requestId: "r.1", kind: "request", payload });
}

for (const quantum of [1, 3, 31, 4096]) {
  test(`fragmented frames preserve canonical identity with ${quantum}-byte chunks`, () => {
    const originals = [frame(1), frame(2)];
    const bytes = Buffer.concat(originals.map(encodeAgentdBrowserFrame));
    const decoder = new AgentdBrowserFrameDecoder();
    const actual = [];
    for (let offset = 0; offset < bytes.length; offset += quantum) {
      actual.push(...decoder.push(bytes.subarray(offset, offset + quantum)));
    }
    decoder.end();
    assert.deepEqual(actual, originals);
  });
}

test("invalid UTF-8 cannot alias a canonical replacement-character payload", () => {
  const bytes = encodeAgentdBrowserFrame(frame(1, { text: "\ufffd" }));
  const body = bytes.subarray(4);
  const index = body.indexOf(Buffer.from("\ufffd"));
  assert.ok(index >= 0);
  const invalid = Buffer.concat([body.subarray(0, index), Buffer.from([0xff]), body.subarray(index + 3)]);
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32BE(invalid.length);
  assert.throws(() => new AgentdBrowserFrameDecoder().push(Buffer.concat([prefix, invalid])));
});

test("decoder failure is sticky after consuming a noncanonical frame", () => {
  const bytes = encodeAgentdBrowserFrame(frame());
  const body = Buffer.concat([bytes.subarray(4), Buffer.from(" ")]);
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32BE(body.length);
  const decoder = new AgentdBrowserFrameDecoder();
  assert.throws(() => decoder.push(Buffer.concat([prefix, body])), /canonical/);
  assert.throws(() => decoder.push(bytes), /canonical/);
  assert.throws(() => decoder.end(), /canonical/);
});

test("clean end closes the decoder without resetting it for another stream", () => {
  const decoder = new AgentdBrowserFrameDecoder();
  decoder.end();
  assert.throws(() => decoder.push(encodeAgentdBrowserFrame(frame())), /closed/);
});

test("partial final input fails permanently instead of allowing repair by append", () => {
  const bytes = encodeAgentdBrowserFrame(frame());
  const decoder = new AgentdBrowserFrameDecoder();
  decoder.push(bytes.subarray(0, 8));
  assert.throws(() => decoder.end(), /partial/);
  assert.throws(() => decoder.push(bytes.subarray(8)), /partial/);
});

test("oversized chunk is rejected even when each announced frame could be valid", () => {
  const bytes = Buffer.alloc(4 * (MAX_BROWSER_AGENTD_FRAME_BYTES + 4) + 1);
  const decoder = new AgentdBrowserFrameDecoder();
  assert.throws(() => decoder.push(bytes), /chunk exceeds/);
});

test("decoded frame count per push is bounded rather than only the residual buffer", () => {
  const bytes = Buffer.concat(Array.from({ length: 65 }, (_, index) => encodeAgentdBrowserFrame(frame(index + 1))));
  assert.throws(() => new AgentdBrowserFrameDecoder().push(bytes), /batch exceeds/);
});

test("maximum frame batch remains usable", () => {
  const bytes = Buffer.concat(Array.from({ length: 64 }, (_, index) => encodeAgentdBrowserFrame(frame(index + 1))));
  const decoder = new AgentdBrowserFrameDecoder();
  assert.equal(decoder.push(bytes).length, 64);
  decoder.end();
});

test("single-byte ingestion does not repeatedly concatenate the accumulated body", () => {
  const bytes = encodeAgentdBrowserFrame(frame(1, { text: "x".repeat(4096) }));
  const original = Buffer.concat;
  let copied = 0;
  Buffer.concat = function (list, length) {
    copied += length ?? list.reduce((sum, item) => sum + item.length, 0);
    return original.call(this, list, length);
  };
  try {
    const decoder = new AgentdBrowserFrameDecoder();
    let frames = 0;
    for (const byte of bytes) frames += decoder.push(Uint8Array.of(byte)).length;
    decoder.end();
    assert.equal(frames, 1);
    assert.ok(copied <= 3 * bytes.length, `${copied} concatenation bytes for ${bytes.length} input bytes`);
  } finally { Buffer.concat = original; }
});
