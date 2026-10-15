# 2026-10-15: exact-head CI failure triage and causal experiment unblocking

**Draft research only / DENY_ALL.** Previous PR #1926 reports repeatedly described queued Actions. The `1a22e114c1c8ea081da51d4e94ccb9ff9ce9aeff` run actually finished, and many real jobs **failed**. This document records the *first* direct remote log triage and repairs, not simulated or historical green results.

## Actual completed predecessor runs

| Exact run | Observed status and source-backed diagnosis |
| --- | --- |
| [E1 real three-Encoder](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668819) | **FAILED**. Granite R2 frozen Encoder and Head run completed. mmBERT-small also emitted a Head report, **but the Transformers load report said `embeddings.tok_embeddings.weight` MISSING / freshly initialized** when loading stock MLM with `AutoModel`; this invalidates any pretrained mmBERT capability claim. EmbeddingGemma 2 then failed with `ModuleNotFoundError: torchvision` when importing `EmbeddingGemma2Processor`. No valid three-way study. |
| [E2 residual](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594669059) and [independent E2 reviewer](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668785) | **FAILED**: CPU Torch was installed without NumPy; tensor `.numpy()` raised `RuntimeError: Numpy is not available`. |
| [E5 crash](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668822), [sparse SGD](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668694), [packed CPU](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668847), [momentum](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668944) | **FAILED** on the same missing NumPy prerequisite. A full Worker/wal/crash acceptance claim was **never** warranted. |
| [blocking-ci](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594669104) | **FAILED**: 12 codespell warnings in MemoryCell/Research code and prose; a dependency-graph test raised a temporary `.git` cleanup error after testing, possibly from automatic Git maintenance. Do not waive required status. |
| [Architecture convergence](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668935) | **FAILED** on prospective base-merge ref check while the multimodal Stem parent continued independently. The source-head lane succeeded. |
| E3 media and E4 reversal | Their exact-SHA narrow research contract jobs **succeeded**, but neither grants production release or real new-task causal E3/E4 utility. |

## Concrete fixes landed in PR #1926

The eight Torch CPU workflows now install pinned `numpy==2.2.6` and the E1 real pretrained environment additionally pins `torchvision==0.25.0` and `torchcodec==0.10.0` matching CPU Torch 2.10.0. All package pins are explicit; the jobs must still run and pass on exact new HEAD.

E1 no longer uses unqualified `AutoModel` for mmBERT. The new `e1_mmbert_tied_loader.py` loads the stock **ModernBertForMaskedLM** model at the original approved immutable revision, checks a full loading report, checks *physical* tied embedding/decoder storage via the upstream V11 strict-alias verifier, and compares **every row** of the loaded 384D pretrained vocabulary against a local pinned safetensors tensor. It rejects any unexpected, mismatched, or unexplained missing weights, nonfinite or corrupt values. This is a local data-integrity proof, **not** independent model publisher signing; the E1 independent numeric scorer refuses a mmBERT arm without this complete source-weight proof. Seven offline adversarial tests cover byte alteration (including a middle row), untied storage, random initialized embeddings and wrong geometry. They are now included in the E1 workflow.

The 12 original codespell issues were corrected **in context**, including a misspelled presentation variable, without changing question/arm semantics; research prose now uses ordinary, correctly spelled descriptions. The temporary-repository regression tests disable Git auto maintenance only inside the test fixtures; assertions, selection rules, and `blocking-ci` remain unchanged.

Parent PR #1885 had **33 new commits affecting 44 paths**, with zero path collision against #1926's changed files. We **incrementally merged** the exact parent SHA `30c36096aa713e3d7098a79c2f080dff2900b684` using unmodified upstream Git blobs and a two-parent Git commit `2ab88d66869193196558d377249dad75d0ed3a84`. Ref update used the previous exact child HEAD as a CAS lease; no force update and no parallel Stem changes were discarded. The new parent also provides an independent strict stock MLM tied-storage identity contract and separate pooling studies, which are preserved.

## Scientific and release blockers that remain

The previous E1 run is **not** a successful three-model comparison: even if Granite's single research arm completed, mmBERT was physically invalid and Gemma was absent. No Stem winner can be selected from it. Exact new-source Actions must recompute all three pinned real Encoder forwards, independently review Head outputs and per-model lifecycle costs; English-only AG News remains a public cross-sectional dataset and cannot become a Chinese/English/code, three-chronological-future experiment.

E2/E5 reruns need green exact-HEAD Actions and raw artifact review; E5's 4096-Cell sparse safetensors checkpoint experiment already exists in `e5_continual_sparse_checkpoint.py`, but its earlier hosted job was blocked by missing NumPy. Native Rust Worker/CAS/FinalUse/WAL revocation, physical target-host p99/energy/GPU, independently reviewed Reader sufficiency, OOD and externally signed future NDU all remain open.

**All research paths stay `DENY_ALL`, `production_promotion_permitted=false`, PR Draft. Do not bypass `blocking-ci`, merge to production or interpret unit/CPU simulations as real language-model utility.**

Machine-readable run references and remediation limits: [E1E5_CI_FAILURE_REPAIR_20261015.json](E1E5_CI_FAILURE_REPAIR_20261015.json).
