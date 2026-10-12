# MemoryCell: three completed frozen Qwen runs — cross-run output stability audit

**2026-10-12 · Actual pretrained model output · exact source and ZIP pins · research NO-GO**

Three previously initiated GitHub Actions runs have finished all **40 original
calibration** and **72 original nine-arm evaluation** generations, with separately
successful read-only replay of each run. This report compares their independently
sealed raw answers; it does not generate answers, pool the runs into extra
independent source families, or change any scoring rule. The same eight authored,
previously exposed development questions occur in each run.

## Evidence provenance and run-state distinction

| Source | GitHub Actions run | Reader + independent replay | Entire workflow | Original output ZIP SHA-256 | Replay ZIP SHA-256 |
| --- | --- | --- | --- | --- | --- |
| A · `82506982` | [38148514657](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38148514657) | Both passed | **Success** | `7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f` | `7e390bddfb1c59e0bb82999b01747a180eb1ec1f84d9f863a536dd036ec483f1` |
| B · `eba9af09` | [38146546731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731) | Both passed | **Success** | `b4cf1346ce4c5b1625cdc57845bcca33fcf82f84340433b602d76258c10c1138` | `4c64e9c01bef56d0f311e633af53c7a246102e7083a272122286fb7ff66085a3` |
| C · `c24fad24` | [38114667490](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114667490) | Both passed | **Failure:** separate PR-wide format job | `2d71f40e553e7d28cad9d8e16803f52b7a99e771b5bf54f55c89bc9468702107` | `fe710be3f987e34ec3cda48be37509e20a01b48db090907c98ce33cfff198225` |

The two complete sharded model artifacts each contain **267 verified manifest
members**; the original nonsharded artifact has **38**. Replay ZIPs contain
one and eight manifest-validated files, respectively. All six outer ZIP SHA-256
pins, the complete internal manifests where present, original source commits,
original model identity, original frozen plan
`9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`,
calibration policy, original journals, strict task results and independently
replayed citation-chain summaries were checked.

The model weights share identity
`f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.
For **all 112** matched question/arm inputs, all three runs delivered the
same ordered original evidence and the same prompt-token SHA; corresponding
answers are nevertheless not always equal.

## Three real executions: task and complete cited-chain results

Every cell is correct answers out of the **same eight authored questions**. A,
B and C are repeats on the same population, *not* 24 independent tests.

| Frozen evidence condition | Run A | Run B | Run C | Complete program-declared citations among correct answers (A/B/C) |
| --- | ---: | ---: | ---: | --- |
| Reader-calibrated Hybrid top-1 | 5/8 | 5/8 | 5/8 | 3 / 3 / 3 |
| Fixed Hybrid top-4 | 3/8 | 3/8 | 3/8 | 1 / 1 / 1 |
| Hybrid top-6 | 3/8 | 3/8 | 2/8 | 1 / 1 / 0 |
| Hybrid top-4 reversed | 2/8 | 3/8 | 3/8 | 0 / 1 / 1 |
| Single-hop selection | 4/8 | 4/8 | 4/8 | 4 / 4 / 4 |
| Full-path entity/time | **8/8** | **8/8** | **8/8** | 4 / 4 / 4 |
| Correction-aware organization | **8/8** | **8/8** | **8/8** | 4 / 4 / 4 |
| Program-designated support | 8/8 | 8/8 | 8/8 | 4 / 4 / 4 |
| No evidence | 0/8 | 0/8 | 0/8 | 0 / 0 / 0 |

Calibration chose **k=1 on each run** using the same preregistered success-
first, prompt-tokens-second objective. This does not cure leave-one-out
instability or confer generalization evidence.

The full-path filter gains four correct answers over single-hop on every run.
The complex organizer gains **zero correct answers and zero complete citation
chains** over full-path filtering. It saves **573 complete prompt-input tokens
out of 5,752** (9.96%) over eight reads, not end-to-end storage or lifecycle
cost. No parametric learning occurs in these reader experiments.

## Inter-run stability is not perfect

The cross-run checker detects **13 distinct frozen inputs** whose generated
text/token SHA differs across the three executions: **4/40 calibration** and
**9/72 evaluation**. Crucially, **two evaluation inputs change strict task
correctness**: one `hybrid_k6` case and one `hybrid_k4_reversed` case.

Within each individual original run, the 39 pairs of arms with identical
ordered evidence were internally consistent. That narrower property does not
establish output-bitwise reproducibility **across** different CPU hosts/runs,
even with matching pinned model bytes, original sources, source order, reader
profile, deterministic-decode configuration and input-token digest. Some drift
is punctuation/citation spacing; two cases change whether the response meets
the registered strict correctness condition. No changed answer is silently
repaired or excluded from the planned denominator.

## Admission decision

**NO-GO for a claim of extra organizer task accuracy or trained/parametric
memory advantage.** The three repetitions support a bounded result on the
same exposed, program-authored task set, not independent source-family
replication. Formal citation-chain coverage is not independently adjudicated
semantic entailment, and **4/8** complete citation chains is not a 99% result.
There are still no independent future windows, operational lifecycle/recovery
costs, authorized production cutover, or signed independent human assessment.
Production acceptance and statistical superiority remain **false**.

The strongest simple full-path source filter must remain the same-reader,
same-tools baseline in any next independently sourced evaluation. New
parameter training or a production activation cannot be justified by this
same-population repeated result.

## Read-only reproduction

Use `scripts/memory_cell/strong_rag_crossrun_audit.py` on the six exact
GitHub Actions ZIPs, in the order **A full, A replay, B full, B replay, C full,
C replay**, with the `--output` destination. The auditor rejects wrong outer
hashes, edited internal manifest members, duplicate JSON fields, altered raw
answers, incomplete 40/72 census, mismatched reader weights, different prompt
IDs, source selection changes and mismatched independent replay statistics.

Machine-readable receipt:
`/scripts/memory_cell/data/strong-rag-three-run-replication-20261012.json`.
Synthetic tests in `test_strong_rag_crossrun_audit.py` are always runnable;
set `HEPTA_MEMORY_CROSSRUN_ARCHIVES` to a directory containing all six exact
ZIPs to execute the additional *actual original model artifact* regression.

The report was created from the completed archived sources; later commits to
PR #1452 must not relabel it as results from those newer HEADs.
