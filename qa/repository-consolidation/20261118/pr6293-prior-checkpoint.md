## Purpose

Audit and consolidate the ordinary Rust branch histories into `main`, while preserving the newly added HIA and Cell research branches. This PR is the active integration workspace. Remaining histories and applicable validation are still being completed.

## Current published state

- Integration and verified PR head: **`5ec371387c47fe1af3cb511c076867ff2678f940`**, published by a non-forced, expected-head update and independently observed on 17 November 2026 at **12:04 UTC**.
- Main remains **`732e934ba496d90fbe042b8d41d479ef901643e5`**. This PR is open and unmerged.
- Latest complete inventory: **7,480 heads**. The ordinary candidate-name set remains **7,230**, excluding main and **249 protected HIA/Cell names**.
- The protected historical/current union contains **259 commit pins**. The published candidate contains **none** of those pins in its ancestry.
- Graph coverage is **1,906 of 7,230 ordinary heads**; **5,324 remain outside this candidate's ancestry**. This count is derived from the previously executed complete 6de ancestry check plus the complete nineteen-commit 6de-to-5ec ancestry difference, with all unchanged ordinary heads and the integration-ref advance reconciled. It is not a claim that every remaining source family has been audited.
- No ordinary branch has been deleted. No main or protected ref has been written.

Two complete API passes at 11:35–11:38 UTC agreed exactly. A further full pass at 12:00–12:01 UTC found no name or SHA change. These are consistent, non-atomic snapshots. Fourteen new Cell online-v4 branches were classified from their complete immutable parent chain into the existing protected Cell family. Both the old and new HIA union29 heads remain pinned. The twenty old ordinary histories whose names contain `hia` retain their previous explicit classification.

Protected-history exclusion is an induction from the earlier full 244-pin ancestry check, the exact additional parent edges and a positive reachable-anchor query. Each of the fifteen new pins descends from an already excluded protected pin. The complete local proof is SHA-256 `cc45f4c6fd1db1c57fd751143bdfc67081cc750aeeb39fad7d0c46708a04f9ba`; this does not represent a new full graph traversal or native-test pass.

## Changes since 6de

[The complete comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/6de3bb36d80f4a1c92f83e9cde7f8b0f496f5e5f...5ec371387c47fe1af3cb511c076867ff2678f940) contains **19 new ancestors and 63 changed paths**.

| Area | Integrated result |
| --- | --- |
| Four original histories | Retain the original RustSec/Fleet, two Q24 assertion and workspace-patch/PTY histories through ordered two-parent merges. Preserve the current stronger Rust implementations; add the reviewed workspace-patch and actual-nextest-report regressions. |
| Existing Ruff workflow | Correct three references to the existing security regression file. |
| Complete CodeQL review | Retain all 198 findings, raw traces and source-pinned review records. No alert is dismissed or suppressed. |
| Memory diagnostic history | Retain both original federation histories and six historical evidence files. The only active Rust delta is three test-only timing blocks; current production code and existing tests remain byte-identical. |
| Windows Bazel selector | Exclude the exact Unix-only readonly manual harness from native Windows Clippy targets. Linux, macOS, cross-compilation and lookalike labels retain their original treatment. |
| Learning qualification | Bind merge-queue evidence to the actual event, head, tree and ordered parents; preserve the original PR/push lanes and run the original Lane E self-test. |
| Windows current CI | Preserve all **175 current cases** in 19 groups across two original-profile native shards: 98 owner cases and 77 process cases. Preserve the exact current fixture, observer and 23 existing tests. Aggregate only exact-source, exact-run evidence from both distinct native runners. |

The Windows union restores the eight current sandbox cases missing from the incoming historical 167-case proposal. The existing operator/shadow selections remain unchanged. Both native jobs retain their original 65-minute limit, single test thread, zero retries and development profile; the aggregate job has a five-minute limit. This increases total runner capacity and does not establish a native pass before execution.

## Executed validation and its limits

| Check | Actual scope and result |
| --- | --- |
| Workspace patch / nextest regressions | **14 passed** on the reviewed source combination. |
| Windows target selector | **22 actual Bash cases passed**, plus two syntax checks, including command failure propagation, CRLF, exact labels and lookalikes. No Windows native execution is implied. |
| Learning queue binding | **18 actual Python/Git tests passed, zero skips**. Pinned style checks passed. The original Lane E self-test ran successfully with its five exact source inputs; the full Lane E verifier was not rerun by those tests. |
| Windows shard evidence | **43 Python tests passed, zero skips**, including each of the eight missing-case negatives, historical/current-scope forgeries and full-175 positive controls. Pinned Ruff, Prettier, spelling and Python compilation passed. Source/control inputs remained unchanged. Native Windows results remain pending. |
| Memory diagnostic | The original focused native truncation test passed **1/1**, with the original two-second/sixteen-peer contract. Exact source manifests and scoped input inheritance are retained. This is not a complete Memory package rerun. |
| AuthBus helper continuation | A separate exact seven-helper continuation passed **7/7** with unchanged inputs. The earlier broad run remains failed and other outstanding failures are not reclassified by this result. |
| Previous full PR blob policy | Main-to-**6de** passed **22,945 A/M paths**, 22,426 required objects, zero missing inputs and zero violations; ten original policy tests passed. That result is retained at its exact head and is not relabeled as a fresh full 5ec check. |
| Previous source/native suites | The original 1,345-case B4 suite, caller proof, 779-case five-package union, separate 399-case Neuron repair and RustSec follow-up remain recorded at their exact earlier source/input scopes. They are not combined into a fictitious new execution. |

The full CodeQL review covers **194 Rust and four Python results**: fixture findings, bounded flows, owned Windows handle flows, intentional output and the reviewed quota-policy boundary. No confirmed defect was established in those reviewed flows. This is not a repository-wide security-clean claim.

## Hosted CI and remaining work

Checks for this newly published head must complete under the unchanged required **CI required** and **Architecture required** rules. Earlier-head successes or failures are not copied onto this head.

Open runtime evidence includes the macOS PTY readiness/output cases, Linux Agentd timeouts and the recorded musl Core failures. The macOS log contains two actual PTY failures out of thirty cases; repeated collector text is not treated as a retry. The previous Windows guard failures and original job timeout remain preserved.

Larger `6cfa`, `c2d` and other source families remain under review. The c032 owner-service and Provider native proposals, optimizer source proposal and unwired context-compiler proposals are not part of this published head. Existing DENY_ALL, HOLD and NoUpdate decisions remain in force. Full original source/native validation, applicable hosted gates and main merge precede ordinary-ref deletion.

## Repository evidence

This head includes the [four original histories and complete CodeQL evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/1dd058df2703d7fd852ffe0b63cd1f3fde23f11a/qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/four-histories-and-complete-codeql): 396 original files preserved as 370 unique objects in 40 bounded carriers, with actual restoration and byte verification.

Earlier retained packages remain available:

- [Whole 5993 source and original native evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/6de3bb36d80f4a1c92f83e9cde7f8b0f496f5e5f/qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/whole-5993-source-union)
- [Neuron arity source repair](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/6de3bb36d80f4a1c92f83e9cde7f8b0f496f5e5f/qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/neuron-arity-source-repair)
- [Final thirty-source combination and original audit](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/6de3bb36d80f4a1c92f83e9cde7f8b0f496f5e5f/qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/final30-source-and-original-audit)
- [Seven follow-up histories and hosted evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/6de3bb36d80f4a1c92f83e9cde7f8b0f496f5e5f/qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/seven-rustsec-and-diagnostic-histories)


