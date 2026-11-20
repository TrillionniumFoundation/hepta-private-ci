# E5 six-candidate metadata and license freeze

This stage records **zero new admitted sources, native test children, model calls or training updates**. It preserves the first eligible selection order and identifies what an authorized content review must resolve.

The intent was published as commit `2da9714aba0288590dbcdc8febdb9ed549f9f5d2` in Draft #6782 before any candidate metadata/license reads. Its parent is the fixed #6777 source `705797ce07ca90ab4c520f0c6ae632b2e783acc8`; this branch has not moved #6777. The six declared names are disjoint from the prior 36 exclusions and 12-candidate roster. No runtime or test files/patches were retrieved in this snapshot.

| Declared repository | Original-order outcome | Exact notice precheck |
| --- | --- | --- |
| coady/multimethod | #157, first result: provisional runtime plus test paths; no native claim | Apache-2.0 notice; before/after identical |
| SethMMorton/natsort | #196, first result: provisional runtime plus test paths; PR reports stub ICU, not a measured result here | MIT; before/after identical |
| Tinche/cattrs | Zero matches under frozen query; declared repository is a fork of python-attrs/cattrs; parent not substituted | MIT at exact declared default head |
| benjaminp/six | #402 documentation and #382 packaging rejected; first unresolved runtime item #365 concerns Python 2 and has no changed test path | MIT; before/after identical |
| python/typing_extensions | #808 CI and #779 documentation/tooling rejected; #760 runtime and test paths require content review to distinguish runtime correction from version/test maintenance | PSF Version 2 plus complete historical and documentation clauses retained; before/after identical |
| jaraco/functools | Exact requested repository returned HTTP 404; no substitute repository used | Unavailable |

`SELECTION_AUDIT.json` retains all first-ten query results, every inspected decision, exact merge/first-parent pairs and all unknowns. The original query is `repo:{repository} is:pr is:merged fix in:title`, created descending, maximum ten. Later results after the earliest unresolved candidate were not inspected. No result was chosen from a student or replay outcome.

The wrapper search returned empty arrays; the canonical GitHub Search endpoint was used with exactly the same query and order. Both responses are in the original archive. GitHub's NOASSERTION repository labels were not treated as absence of a license: the exact repository notices were read and retained, with Git blob and SHA-256 checks. This is a notice identity precheck; dependency/file-specific licensing and native source admission remain open.

`LICENSE_BINDINGS.json` binds nine exact-ref retrievals to five byte-identical notice files in `licenses/`. `METADATA_ORIGINALS_MANIFEST.json` binds every original JSON response to `metadata-originals.tar.gz`. All archived member lengths and SHA-256 values have been verified. Original errors and no-candidate outcomes remain in the archive.

Any content/native continuation must preserve the frozen selection rule, exact source identity, complete upstream parameter sets, original before-failure/after-pass requirement and original child budgets. Metadata does not qualify E5 source growth or close the 16-source material gate.
