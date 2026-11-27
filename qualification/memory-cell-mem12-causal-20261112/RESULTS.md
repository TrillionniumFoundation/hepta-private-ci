# MEM12: unified native candidate and frozen causal execution checkpoint

> Recovery update: the original run and all 1,420 indexed artifacts have now been recovered and independently checked. All 80 generations returned; all ten frozen primary scores remain 0/8. See [RECOVERED_RESULTS.md](RECOVERED_RESULTS.md). The checkpoint below preserves the earlier UNKNOWN observation and is not the current outcome.

## Decision

**HOLD. The source composition, software controls and remote preparation are verified. The real campaign launch acknowledgement and its outcomes are UNKNOWN.**

As of 2026-11-12 07:05:36 UTC, the retained evidence supports **zero independently verified scored rows from this new campaign**. It does **not** support saying that zero model calls occurred. A timed-out launch response may have followed an actual launch. No new operation key has been used to repeat the campaign.

This checkpoint preserves the original commands, timeout responses, exact helper bytes, successful preparation readback, fixture test logs and native validation handoff. It is not a positive or negative estimate of memory benefit.

## Exact candidate and review stages

Execution source: `811e0e27190066e81a23eebed8ad559ae67d228e`.

Complete tree: `2043cbf11fd00662cc23562123c27ae4e6f72580`.

| Stage | Review | Result |
| --- | --- | --- |
| Importer, native revocation and Attach/Withhold composition | [#6142](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6142) | Exact original postimages from #5972 and #5977 retained across all 13 affected paths; infer-worker-host CI coverage added |
| Provider input records and replay validation | [#6158](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6158) | Captures the rendered prompt and all generation-entry tokenizer tensors; rejects forged replay receipts with invalid isolation/runtime/source bindings |
| Fixed intervention runner | [#6176](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6176) | Frozen source roster, actor, parser, model, limits, arm ordering and complete planned denominator |
| Original evidence binding and orchestration controls | [#6177](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6177) | Validates original A writer, C actor, provider admission and raw outputs before scoring; existing arm directories are not rerun |

The component postimage check proves exact source composition. It does not transfer historical test results onto this candidate or establish an ordinary production owner path.

## Fixed causal design

The frozen plan contains eight generated sources, three arbitrary parcel-to-color assignments per source, one shared task template and ten arms. At most 80 generation rows can result. These are **eight paired sources, not 80 independent memory-benefit episodes**.

A deterministic A process writes a research SQLite store, then exits. Each C actor and model process is fresh. The A request contains source facts; future C questions, scoring truth and replacement targets are excluded from A's request. C receives a public question and only the memory bytes permitted by its arm. The public whole-output color parser is frozen and is never given the expected answer.

| Arm | Intervention | Intended comparison |
| --- | --- | --- |
| `on_bm25` | Retain, retrieve with BM25 and deliver | Reference; this is the BM25/RAG baseline itself |
| `off` | Full research memory-off path | Overall access to retained memory |
| `retention_off` | Discard retained state for C after the common A write | Retention; does not save the already incurred A cost |
| `delete` | Remove only the relevant record | Dependence on relevant retained content |
| `replace` | Replace that record with an incorrect value; preserve original scoring truth | Content dependence; wrong-value following is reported separately |
| `retrieval_off` | Keep storage, stop retrieval | Retrieval |
| `delivery_off` | Keep storage and retrieval, withhold delivery | Delivery; not full memory-off |
| `exact_kv` | Exact key lookup | Retrieval/selection comparison under common caps |
| `finite_icl` | Finite retained context | Retrieval/selection comparison under common caps |
| `uniform_replay` | Frozen uniform sampling | Retrieval/selection comparison under common caps |

Common caps are two records, 2,048 context bytes, 1,024 model input tokens and 32 output tokens. Each model subprocess has a 60-second deadline. The outer campaign deadline is 7,200 seconds and includes setup and evidence work. Equal caps do not imply equal observed tokens, elapsed time or work. The report retains observed cost totals plus observed and missing row counts; unavailable cost is never imputed as zero. The common A writer cost is charged once and shown separately.

The actor and model have fresh HOME, work, cache and tmp locations and distinct user, network, PID, mount, IPC and UTS namespaces. Known prior task state, repository files, A databases and old conversations are not mounted into C. Fixed runtime and system libraries remain read-only visible. This closes the known task-state bypasses; it is not a claim that all filesystem capability is absent.

The provider retains exact request bytes, the rendered prompt and all input tensors immediately before `model.generate`. This does not claim a trace of every internal forward pass. The report re-reads original provider logs and inputs and recomputes the score rather than trusting a cached score field.

## Verified preparation

The preparation job `1a1ce87be7a-2564-16e3`, under key `mem12-causal-prepare-20261112-ef0c-v1`, returned an authoritative succeeded state, exit code 0, no timeout and complete durable output.

Its readback confirms:

- The exact candidate commit and complete tree above, in an independent source directory.
- The fixed local model `SmolLM2-135M-Instruct@12fd25f77366fa6b3b4b768ec3050bf629380bac` and all eight model asset hashes.
- Runtime inventory SHA256 `d0814616180cc42103dbae19274f2a63fc02b7da75fd82d3d49ddd4553d0d76a`, covering 1,071,646,901 bytes, 26,827 files and 29,573 entries.
- A strict namespace preparation probe with status `EXECUTED`.
- A pre-generation plan of 10,624 bytes, SHA256 `f623a23197fe94b3d5434ffac1f02cb3d99398ca4c69aad18716dbeeef1b2d82`.
- Zero model calls during preparation.

The probe is a preparation observation; it does not replace the separate eight-case strict isolation qualification.

## Real execution state

| Field | Observed value |
| --- | --- |
| Original campaign key | `mem12-causal-execute-20261112-ef0c-v1` |
| Remote evidence root | `/home/qq/work/mem12-causal-20261112-ef0c` |
| Launch response | MCP request timeout; job identity not yet recovered |
| Subsequent summary/archive read | MCP request timeout |
| Bounded durable job metadata read | MCP request timeout |
| Closed asynchronous read admission | MCP request timeout; admission identity UNKNOWN |
| New physical model calls | UNKNOWN |
| Independently verified scored rows | 0 |
| Correctness, paired effects and measured costs | UNKNOWN; no estimate published |
| Repeated campaign under a new key | No |

The exact filled preparation helper is SHA256 `89e7c6819353543d30e393231d43828d40f07a191cb07087b105d62a69a983e1`; the exact run helper is SHA256 `dd88e2331b09964b238cf729af4fdad4abee2fe960b0443f1e4378b44fd6755f`. Both are retained with the submitted arguments. The run helper preserves unknown costs and includes source/helper originals in the remote evidence archive. An archive failure must be repaired by reading existing originals, never by repeating generation.

## Software controls and native execution limits

Eight diagnostic orchestration tests passed in 7.208 seconds, with no failures or skips. They exercised real A subprocesses and mock provider results, including missing rows, tampering and refusal to rerun existing arms. These tests made zero model calls. Repository formatting preserved all four Python ASTs; final file hashes are included and match the execution source.

The underlying provider stage separately records 122 software controls and a recovered historical greeting. See [provider RESULTS](../memory-cell-mem12-provider-20261112/RESULTS.md). Those results do not supply causal benefit scores for this campaign.

The final native validation was submitted once under `mem12-native-final-811e0e27-20261112-ef0c-v1`, with Cargo jobs limited to two and nice set to 10. Its acknowledgement and results are UNKNOWN. The final strict eight and native contracts are therefore not marked passed.

A collection defect was found in the submitted native runner: it looked for JUnit under the source tree despite setting a separate `CARGO_TARGET_DIR`. The expected report location is under the configured target directory's `nextest/local/junit.xml`. The original runner and any resulting failure are preserved. Recovery must locate original JUnit and bind its UUID/time to the original supervisor receipt; it may continue only stages proved not to have run. Completed tests must not be repeated to conceal a collection failure.

At the retained CI observation, Codespell succeeded on the exact execution source; native, strict, Python and other blocking checks remained queued. A queued check is not a successful qualification.

## Scientific boundaries

This is a new controlled text diagnostic with a Python research SQLite owner. It is not the earlier MEM5 OCR actor/public selector, not a natural-task generalization result, and not an executed production native owner chain. It must not be pooled with the earlier 30/84 versus 28/84 or 21/54 versus 13/54 cohorts.

The frozen BM25-on arm cannot demonstrate superiority over BM25 itself. Retention, retrieval, selection and delivery have separate interventions. Withhold alone is not memory-off. No trained association, weight consolidation or model adoption is justified by these controls. Missing-label bounds, if eventually emitted, are descriptive identification bounds rather than confidence intervals.

## Recovery contract

1. Recover the original job or retained `RUN_SUMMARY.json`, `ARCHIVE.json` and full cohort originals. Do not replace the campaign key or modify the frozen source, actor, parser, cases or limits.
2. Verify the remote archive SHA256, every indexed member, plan pin, source pins, A/C temporal ordering, isolation observations and actual model input records.
3. Independently recompute every planned row and paired contrast. Preserve failures, malformed answers, timeouts, missing outcomes and their denominator.
4. For each source, compare actual request bytes and tokenizer tensors across `off`, `retention_off`, `retrieval_off` and `delivery_off`; all four empty-delivery requests should match. Compare output consistency without treating four copies as independent evidence.
5. Report replacement following separately from correctness against original truth. Report actual costs, common A cost and unavailable costs explicitly.
6. Recover native test originals separately, including the JUnit collection defect. Source composition, native control tests, strict isolation and real model outcomes remain separate claims.

## Retained artifact

`checkpoint.tar.xz` contains 49 indexed original files plus its index. Size: 74,244 bytes. SHA256: `0f950ea225f41d38c1c21e1e20cb3826037e5841386750a25832e1ca5d5c7af8`. Every indexed member was read back and verified. `EVIDENCE.json` provides the machine-readable checkpoint.
