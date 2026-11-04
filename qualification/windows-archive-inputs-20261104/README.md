# Native Windows compiler archive inputs

Original native Windows Clippy on source `3cc71d6ec7e5e084dcecceb2757bc940459f0ada` analyzes the complete 1,282-target selection but builds only 1,276. The real failure is a process-wrapper copy of `exec-server.lib.temp-archive-9c734b8.a` after that temporary file disappears. The original tested merge has exactly the source tree. Its complete decoded log is retained losslessly in two bounded gzip parts; `evidence.json` gives the order, hashes and exact source identity.

The existing Windows wrapper consolidates dependency directories before launching rustc. Its current temporary-output filter covers `.tmp` and `.rcgu.o`, but misses LLVM's atomic archive-writing name. This change extends that existing filter only to an archive basename ending in `.lib`, `.rlib` or `.a`, followed by `.temp-archive-`, exactly seven ASCII hexadecimal characters and final `.a`. All ordinary inputs and all real directory, hard-link and copy failures keep their existing behavior. No retry, error suppression, target exclusion, concurrency reduction or budget change is added.

The patch applies to pinned rules_rust `f19661ba71f77c993ce1eb082053692610fe4313`. Exact hunk contexts and counts were applied independently in JavaScript and the resulting source hashes recorded. This is not a claim of local Rust or Bazel execution.

## Required native acceptance

The existing upstream `@rules_rust//util/process_wrapper:process_wrapper_test` target must run unfiltered and freshly. Linux retains all 18 original tests. Native Windows must run all those tests plus one real filesystem regression, for 19 total. Both require zero failures, ignored or filtered cases and exact original test names.

The new regression writes ten final or similar archive names and five temporary names, invokes the actual consolidation function, reads every retained file byte-for-byte, and checks the exact destination entry count. It is a deterministic classification regression; it does not simulate a concurrent rename stress campaign.

The qualification also checks the actual materialized upstream main and test source hashes and runs fixed Rust1.96 rustfmt on the new test. Actual original committed-lock check, generator and post-check must all pass, with the entry lock equal to HEAD and a clean tracked checkout before and after. Complete original log/XML, command outputs and source inventories are retained.

The fresh original full native Windows Clippy job remains required to close the observed 1,282-target build failure. These unit tests alone do not qualify that job, unrelated product tests or whole private-ci.

Posture: **Draft / HOLD_NO_GO / DENY_ALL**. No local executor is available; no local toolchain execution, main merge, release or activation is claimed.
