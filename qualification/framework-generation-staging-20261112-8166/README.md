# Generation record staging: original qualification evidence

This evidence tree is not itself the tested runtime source. Preserve each run's
exact source/tree and overall result.

| Source | Tree | Run / job | Native tests | Overall result |
| --- | --- | --- | --- | --- |
| `445a28cb3debceca7d53ddae8e04592242662f8e` | `b021eee3528526ce4ee6cc36129b8eefe7af7f90` | 43127114625 / 130881896252 | 43 infer-core + 53 hepta-types passed; 0 failed; 1 skipped | **FAILED**: four formatter whitespace changes |
| `21d2699b7ac7831f355f5acb9570a90da077dbe3` | `f405f505bbea56e9c19b48f41267c8a75df5207b` | 43127681844 / 130883821365 | 43 infer-core + 53 hepta-types passed; 0 failed; 1 skipped | **PASSED**: native, formatting and unchanged-source checks |

The two new original-owner tests passed independently on both exact sources:
`generation_transitions_preserve_unrelated_result_buffers` and
`failed_generation_append_fences_without_installing_staged_state`.
These are controlled filesystem/state tests, not model training, real provider
execution, physical power loss, benchmark improvement, or production acceptance.

Each run's four retained command logs are recovered from the complete decoded GitHub
job log by removing only the GitHub timestamp prefix. Every complete UTF-8 log
was checked against the byte count and SHA-256 emitted by its original
`hepta_ci_exec` execution receipt. All eight matched exactly. The companion JSON
files retain those original console receipt objects, formatted for inspection;
they are not newly issued owner attestations.

The original source-and-record artifact is
[13902948575](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43127114625/artifacts/13902948575),
108,945,958 bytes, SHA-256
`9a36cb363e8c90f61fb6b8d6851c7acc323b0ff83b7979b2d286542de7118049`.

Successor `21d2699b7ac7831f355f5acb9570a90da077dbe3` applies only the four
actual formatter postimages. Its independent native run passed **96 tests with
0 failed and 1 skipped** and the formatting check passed. Command execution took
26.897 seconds; this is test execution time, not a performance benchmark. Its
original source-and-record artifact is
[13903778272](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43127681844/artifacts/13903778272),
108,952,161 bytes, SHA-256
`3e01dcaf1a6794aa6481ecb890b37a1285cd6a7491c2f2db997c6bf54a2b2ed6`.
The attached local executor was unavailable, so no local test/format/lint result
is claimed. Aggregate CI and any later combined candidate require their own
exact-source qualification.

The implementation does not add fair admission, encoder reuse, batching,
concurrent journal handles or compaction. It preserves full cold-history replay,
per-event durability, original owner/token identity and UNKNOWN semantics while
avoiding copies of unrelated retained generation results.
