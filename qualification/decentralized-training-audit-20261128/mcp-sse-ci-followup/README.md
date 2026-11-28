# MCP SSE CI follow-up evidence

This package retains six complete tool-decoded GitHub job logs, compressed without altering their UTF-8 bytes. Each gzip was decompressed and compared to the original before packaging. INDEX.json records the raw and compressed byte counts and SHA-256 values.

The restricted HTTP workflow checked the exact source head abaa4fc0eb4d87f0dd2d9e1b3bcdb0c5620de261, tree 2fc3b7caa9c223f6ebdc189dc891c52faead86eb. Its five existing suites passed 9, 3, 12, 19 and 3 native controls, respectively (46 total). ABAA_HTTP_SUMMARY.json retains the original execution records and their separate native JUnit collection records. Elapsed command times include compilation.

Generic CI checked prospective merge fa49613b9a21a5d86cd577f09ed8dd171479203c, merging that source head into c076d74a013a9be0b969fd42c3932fdcee74e3f0. The Linux GNU job records the new mcp_sse_local_failures test target passing in 1.4 seconds without a cache label. The source defines four cases; the standard job log does not print the individual successful case names. The MUSL job reused that result. The rmcp-client unit target passed from cache, so this is not a claim that the eight new unit controls ran fresh in this job.

The new SSE fixture still violated the existing Clippy expect_used rule at two helper locations. The pending repair returns the fixture server's I/O result, observes task completion during cleanup, and uses an asynchronous mutex for its request ID. It preserves the four test scenarios, assertions, limits and deadlines. The attached independent review is static. The repaired candidate has a successful explicit Rust 1.96.0 rustfmt run and check; its native tests and Clippy have not been rerun locally. A separate root-coordinated formatting result may follow.

The BUILD.bazel attribute-order problem and five Python formatting problems were already byte-identical in base c076d74 and source abaa. Their correction changes formatting only; no checker or threshold is relaxed.

The complete generic jobs still fail. Other failures include five proxy/OAuth-related native targets and TypeScript MCP conformance. The 46 successful restricted controls do not establish that every proxy or OAuth path works. Cargo-deny's original hosted diagnostic was not obtained: the connector returned Transport closed. The retained tool error must not be presented as a GitHub job log or as proof that its failure matched a separate local RustSec reproduction.

These records qualify source-bound engineering observations only. They grant no production activation, FinalUse permission, reward eligibility, learning-utility claim, or end-to-end PoUW qualification.
