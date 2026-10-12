# MemoryCell — Real nine-arm frozen Qwen reader evidence (2026-10-12)

> **Research-only, previously exposed authored development tasks.** This note is a factual result receipt, **not** a model promotion, independent future-source trial, citation-entailment certificate, or production acceptance. Qwen2.5-3B use remains subject to its published research license.

## Generating source and cryptographic record

- Exact *generating* Git commit: [`6304b451268c73f3d1a605985226b102df841bbf`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/6304b451268c73f3d1a605985226b102df841bbf). Later PR HEAD checks **must not** be substituted for the generating source.
- Hosted run: [#38224780900](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900). Its pinned **reader** and **experiment-format** jobs completed successfully; the separate `independent-replay` job was **queued at this observation**.
- Real reader artifact `11743043427`, outer ZIP SHA-256 `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8`. Original event input artifact `11669174727`, outer ZIP SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`.
- Original frozen eight-test plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`; generating model inventory identity `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.
- Both downloaded archives independently passed their full SHA256SUMS file-census checks: **43 model records + 35 frozen original input records**. Calibration raw journal SHA-256 `1b5c774d97656fbbbba9ae668df6e93ea4ca5c75f588bbd0a7424a0fa2be3fc3`; evaluation raw journal SHA-256 `536cae1bf9807bc9caf9ef42d0a4d541152bfbc5ab798146550fdc7d7901b5e9`.

## Real calibration (40 of 40 executed)

| k | Strict successes of eight | Full prompt input tokens |
| ---: | ---: | ---: |
| 1 | 4/8 | 4,045 |
| 2 | 4/8 | 6,328 |
| 3 | 4/8 | 8,698 |
| 4 | 4/8 | 10,970 |
| 6 | 2/8 | 15,708 |

The preregistered success-first, input-token-tiebroken choice is **k=1**. Leave-one-out calibration reselected k=1 in **7** folds and k=2 in **1** fold. Therefore the selected top-k is **not stable** to withholding one calibration question. This is a sensitivity diagnostic on the same authored development corpus, not independent cross-family evaluation.

## Real nine-arm frozen Qwen evaluation (72 of 72 executed)

| Arm | Strict correct | Prompt input tokens | Recorded reader seconds | Correct with all program-declared cited sources |
| --- | ---: | ---: | ---: | ---: |
| `selected_k` (强 RAG 校准 top-1) | **5/8** | 3,961 | 62.51 | 3/8 |
| `hybrid_k4` (Hybrid top-4) | **3/8** | 10,806 | 136.04 | 1/8 |
| `hybrid_k6` (Hybrid top-6) | **2/8** | 15,463 | 194.10 | 0/8 |
| `hybrid_k4_reversed` (Hybrid top-4 反向) | **3/8** | 10,806 | 135.83 | 1/8 |
| `single_hop` (单跳证据) | **4/8** | 4,575 | 66.04 | 4/8 |
| `entity_time` (实体/时间完整路径) | **8/8** | 5,752 | 79.20 | 4/8 |
| `organized` (版本纠错组织化) | **8/8** | 5,179 | 73.52 | 4/8 |
| `program_support` (程序声明支持集) | **8/8** | 5,179 | 73.11 | 4/8 |
| `empty` (无证据) | **0/8** | 1,630 | 36.14 | 0/8 |

**Paired results:** `entity_time - single_hop`: **4 wins / 0 losses / 4 ties**; `organized - entity_time`: **0 wins / 0 losses / 8 ties**; `organized - hybrid_k4`: **5 wins / 0 losses / 3 ties**; `selected_k - hybrid_k4`: **2 wins / 0 losses / 6 ties**. These are fixed eight-task contrasts, not confidence intervals or independent proof of generalization.

The full-path `entity_time` condition solves all four two-hop composition/procedure questions that `single_hop` misses; correction-aware `organized` does **not** add strict answer successes over the already full-path selection. `organized` saves **573 of 5,752 input tokens (9.96%)** relative to `entity_time`, but read-time and total production lifecycle cost cannot be inferred from this sample alone.

**Citations are a separate gate:** Both `entity_time` and `organized` have 8/8 strict answers but only **4/8 correct answers cite every program-declared support source**, under the *formal authored-program definition*. Neither 4/8 is a human semantic citation-precision estimate. The frozen reader generated **39 identical-ordered-source answer pairs without output disagreements**.

## Independent read-only local replay performed in this turn

A separate Python process executed the generating artifact's actual `strong_rag_receipt.py`, the frozen original `event_experience.py`, `event_projection.py`, original isolated `event_probe.py`, `strong_rag_hop_control.py`, `strong_rag_stability.py`, `strong_rag_repeatability.py`, and formal citation-chain module. For non-model dependencies unavailable locally it used **minimal interface-equivalent replay shims**, not different scoring/selection algorithms or a model. It did not load or generate Qwen answers.

- Rechecked the complete 35+43 inner manifest pins and exact commit.
- Recomputed **112/112** raw answers and stored scores; **re-executed all constrained procedure requests** and compared stdout, stderr, exit status and request.
- Rebuilt held-out single-hop controls using *public question specifications and original evidence*, not the test answer labels.
- Rebuilt each unsigned native citation payload, including original excerpt bytes, request SHA, prompt digest, explicit root derivation, and exactly recomputed formal citation-chain audit.
- Independently recalculated top-k calibration, leave-one-out stability, paired contrasts and 39 same-prompt comparisons. An altered scored outcome and an altered original evidence excerpt (even with modified inner manifest checksums) were both **rejected** by the verifier.

This is strong **local source-compatible software replay evidence**; it is **not** the hosted independent GitHub `independent-replay` job, authenticated third-party adjudication, new prospective task population or independent statistical validation. That hosted job's final success/failure must be checked separately and an unexpected failure reconciled before claim promotion.

## No-go and next experimental budget

Do **not** promote a parametric MemoryCell on these data. Prefer new independently collected source families and matched-reader task/citation evaluations comparing tuned RAG vs single-hop vs full-path vs correction-aware organization. No real-world retention/revocation/recovery lifecycle costs, independent citation entailment ≥99%, parametric memory gain, or production cutover evidence have been established.

## Independent standard-library replay without model dependencies

An additional **separately implemented Python standard-library verifier**
was executed on the original GitHub artifacts (not generated answers, not
the repository's original verifier, and no model/Transformers/PEFT loaded).
The check consumes the two original ZIP archives and reproduces the fixed
source-to-answer/evaluation evidence without inventing source labels:

- Real reader ZIP: `11743043427`, whole ZIP SHA-256
  `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8`.
- Original source ZIP: `11669174727`, whole ZIP SHA-256
  `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`.
- Full two-ZIP inner manifests: **43 + 35 = 78 source/receipt entries**
  verified; all 40 calibration and 72 evaluation original raw/scored rows
  matched without permitted alteration of the reader's original answers.
- Each delivered evidence excerpt, byte offset, source ID/root/scope,
  deterministic event projection and unsigned citation-source root mapping
  was checked against the 108 exact original event documents.
- The pinned original bounded `event_probe.py` was independently invoked
  **28 times** to compare each scored procedure request, exact stdout,
  stderr and exit status. The success-first/token-second calibration
  reselected **k=1**, and 39 same-source-prompt pairs matched byte/token
  generation identities. New scorer replay agrees with all nine accuracy,
  input-token, reader-seconds and program-declared citation-chain aggregates.
- Six tests passed, including forged scored outcome, malformed answer
  grammar, duplicate/nonfinite JSON and changed archive checksum rejection.

The standalone local replay program SHA-256 was
`2fa03157f7dd230585d16959f424cc2e01a69791a06e59ac6448ed3aee1cd20a`;
its six-test file SHA-256 was
`686cc2317eaa7b146e2e2817c328d844659027d3695ec8f2fe5797aa508dd966`,
and the emitted exact JSON receipt SHA-256 was
`ee1be50023f9b8f7d2cef8f98cd05ef15d0dc2b1433029b24345b14547e84db4`.
These local supplemental files are separate conversation deliverables; the
original repository-native verifier, replay job and pinned ZIP artifacts
remain authoritative for the hosted research workflow.

This **does not** attest that the independent hosted `independent-replay`
job for #38224780900 has completed; that job was still queued at this
recheck. It is neither human semantic entailment adjudication nor
independently sampled prospective task validation. The prior four-run
replication report documents 13/112 cross-host prompt-output differences;
repeat executions of these eight authored questions cannot substantiate
generalization, 99% semantic citation precision, parametric-memory gains,
or production acceptance.
