# SQLx Chrono dependency removal

The exact candidate removes the unused SQLx chrono workspace feature and its four resolved Cargo.lock dependency edges. No Rust product source, timestamp representation, migration, test method, assertion, retry policy or skip configuration is changed.

The original fourteen-owner just test --locked --offline gate ran from the a05499eb5d2b2088de6a192d0c42ce9ba0249882 source with these two candidate files: **2,179 tests passed, 16 existing skips, seven slow tests, zero failures**. The previously failing signed recovery frontier test passed. The earlier 2,178-pass/one-failure run remains complete in original-14-owner-failure.log.gz.

The required just bazel-lock-update ran with Bazel 9.0.0 and passed; MODULE.bazel.lock remained byte-identical. Original dependency warnings remain in the raw log. The required just fmt and git diff --check passed.

The original network fetch timed out before checkout or source changes. Recovery restored the exact Git blobs, original commit bytes and original GitHub merge signature, verified their object IDs and complete resulting tree, then checked out the original a054 commit. The source receipt retains this provenance and the fetch failure.

This is a dependency edge cleanup qualification. Current HIA native37, full-product/default-release qualification, platform coverage and legacy retirement remain separate requirements. No whole HIA rewrite is claimed.
