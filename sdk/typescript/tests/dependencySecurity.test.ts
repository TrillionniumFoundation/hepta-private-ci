import { createRequire } from "node:module";

import { describe, expect, it } from "@jest/globals";

const sdkRequire = createRequire(import.meta.url);
const compilerRequire = createRequire(sdkRequire.resolve("ts-jest"));
const handlebars = compilerRequire("handlebars") as {
  compile(
    input: unknown,
  ): (context?: Record<string, unknown>, options?: Record<string, unknown>) => string;
  parse(input: string): { body: { program: { blockParams: unknown } }[] };
  precompile(input: unknown): string;
};
const mcpRequire = createRequire(
  sdkRequire.resolve("@modelcontextprotocol/sdk/server/streamableHttp.js"),
);
const expressRequire = createRequire(mcpRequire.resolve("express"));
const proxyAddr = expressRequire("proxy-addr") as {
  compile(subnets: string | string[]): (address: string) => boolean;
};

describe("security boundaries in the SDK development dependency graph", () => {
  it("rejects forged AST block parameters before compilation and preserves normal templates", () => {
    // GHSA-8r5x-fm3f-whwj: use an inert expression, never shell/process access.
    const ast = handlebars.parse("{{#missing}}{{/missing}}");
    const [block] = ast.body;
    if (!block) {
      throw new Error("expected the parsed block statement");
    }
    block.program.blockParams = { length: "(()=>{throw new Error('unvalidated AST')})()" };
    expect(() => handlebars.compile(ast)({})).toThrow(/Invalid AST/);
    expect(() => handlebars.precompile(ast)).toThrow(/Invalid AST/);
    expect(handlebars.compile("Hello {{name}}")({ name: "<cell>" })).toBe("Hello &lt;cell&gt;");
  });

  it("does not expose a prototype's constructor with inherited methods enabled", () => {
    // GHSA-p8wg-vrv2-v86f: check exposure without executing the constructor.
    const render = handlebars.compile('{{lookup (lookup fn "__proto__") "constructor"}}');
    expect(render({ fn: () => "ordinary" }, { allowProtoMethodsByDefault: true })).toBe("");
    expect(handlebars.compile("{{constructor}}")({ constructor: "ordinary own data" })).toBe(
      "ordinary own data",
    );
  });

  it("does not trust arbitrary IPv4 clients through a short mapped IPv6 subnet", () => {
    // GHSA-jqcg-44mw-7w3h: exercise both the single and multi-subnet paths.
    for (const subnets of ["::ffff:10.0.0.0/8", ["::ffff:10.0.0.0/8", "127.0.0.1/32"]]) {
      expect(proxyAddr.compile(subnets)("203.0.113.19")).toBe(false);
    }
    const trust = proxyAddr.compile("::ffff:10.0.0.0/104");
    expect(trust("10.1.2.3")).toBe(true);
    expect(trust("203.0.113.19")).toBe(false);
    expect(proxyAddr.compile("::/1")("203.0.113.19")).toBe(false);
  });
});
