import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import {
  AgentdBrowserFrameDecoder,
  buildAgentdBrowserFrame,
  canonicalAgentdBrowserJson,
  encodeAgentdBrowserFrame,
} from "../src/agentd-protocol.js";
import {
  WorkerFrameDecoder,
  buildWorkerFrame,
  canonicalWorkerJson,
  encodeWorkerFrame,
} from "../src/worker-protocol.js";

// These exact vectors also appear in browser_servo_protocol_tests.rs. v1
// uses UTF-8 key ordering and finite mathematical safe integers, not RFC JCS.
const vectors = [
  {
    input: { "2": "two", "10": "ten", "𐀀": "astral", "": "private" },
    expected: '{"10":"ten","2":"two","":"private","𐀀":"astral"}',
  },
  {
    input: { nested: [-0, 0, Number.MAX_SAFE_INTEGER, Number.MIN_SAFE_INTEGER], floatInteger: 1.0 },
    expected: '{"floatInteger":1,"nested":[0,0,9007199254740991,-9007199254740991]}',
  },
  {
    input: { nested: { "2": "two", "10": "ten" }, text: "\b\f\n\r\t\"\\😀" },
    expected: '{"nested":{"10":"ten","2":"two"},"text":"\\b\\f\\n\\r\\t\\\"\\\\😀"}',
  },
];

const protocols = [
  {
    name: "Agentd", canonical: canonicalAgentdBrowserJson,
    frame: (payload) => buildAgentdBrowserFrame({ sequence: 1, kind: "request", requestId: "request.1", payload }),
    encode: encodeAgentdBrowserFrame, decoder: AgentdBrowserFrameDecoder,
  },
  {
    name: "worker", canonical: canonicalWorkerJson,
    frame: (payload) => buildWorkerFrame({ sessionId: "profile.1", generation: 1, sequence: 1, kind: "dispatch", requestId: "operation.1", payload }),
    encode: encodeWorkerFrame, decoder: WorkerFrameDecoder,
  },
];

for (const protocol of protocols) {
  test(`${protocol.name} canonical bytes match Rust UTF-8 and integer golden vectors`, () => {
    for (const { input, expected } of vectors) {
      assert.equal(protocol.canonical(input), expected);
      const frame = protocol.frame(input);
      assert.equal(frame.payloadDigest, createHash("sha256").update(expected).digest("hex"));
      const decoder = new protocol.decoder();
      const [decoded] = decoder.push(protocol.encode(frame));
      assert.equal(protocol.canonical(decoded.payload), expected);
      decoder.end();
    }
  });

  test(`${protocol.name} canonical numbers reject fractions, non-finite values and unsafe integers`, () => {
    for (const value of [0.5, Infinity, -Infinity, NaN, Number.MAX_SAFE_INTEGER + 1, Number.MIN_SAFE_INTEGER - 1]) {
      assert.throws(() => protocol.canonical({ nested: [value] }), /safe integers/);
    }
  });
}
