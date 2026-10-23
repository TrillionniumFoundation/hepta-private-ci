# Hepta Memory A–I acceptance: a nine-arm, source-sealed research gate

**Status:** Research-only, historical LoCoMo cohort, `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.
**Date:** 2026-10-23.
**Parent:** research PR #3125, exact pinned head `7aac712474b850858d4d72b46419e39a3315d200`.
**Source:** LoCoMo 10 conversations / 1,986 questions, original SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` (CC BY-NC 4.0; respect license and avoid publishing the raw corpus).
**Inherited historical retrieval plan:** `62216f4a7b69fb9f27e087b49daa5249bfb485e99ef96b88123d8fb8b025ff2f`.

This adds an **executable acceptance protocol**, not nine complete model pipelines, not a stronger-Reader result, and not a new published original-model run. Existing P37 news-trained Heads, Procedural file-program Heads, LoCoMo episodic retrieval, Router and split experiments train on **different tasks**; their scores cannot be concatenated into a single memory-quality comparison. The prior LoCoMo cohort was already studied, so this plan is a **post-hoc, frozen historical replication protocol**, not independent prospective evidence.

## Arm matrix and causal contrasts

| Arm | Mechanism | Declared minimum actual observation |
| --- | --- | --- |
| A | BM25 | Source-only lexical retrieval; no neural/graph features |
| B | Dense + BM25 + Reranker | Actual dense and reranker forward receipts |
| C | Graph retrieval | Actual graph traversal receipt |
| D | Typed Memory, no local training | Typed index lookups; no local parameter updates |
| E | Shared Encoder + single trained Head | Physical Head artifacts, positive gradient updates |
| F | Shared Encoder + multiple typed trained Heads | At least two real Heads, same pinned Encoder |
| G | F + learned sparse Router | Real trained Router, positive selected-only Router work |
| H | G + learned Meta-Graph | Positive graph-training updates and graph traversals |
| I | H + split/merge evolution | Both executed split and merge, generation/lineage proof |

Eight predeclared comparisons: `D-C`, `E-D`, `F-E`, `G-F`, `H-G`, `I-H`, `I-B`, `I-C`. Primary retrieval diagnostic is **conversation-macro all-annotated-evidence support recall**, under eight source turns and 4,096 bytes per accepted context. This is **not** answer correctness, graph causal inference, production trust, or deletion certification. Pre-register answer correctness and independent evaluator criteria in a separate **fresh** study before inspecting its gold.

Holdout is the original six LoCoMo evaluation conversations, with two development and two calibration conversations. Questions within the same conversation are **not independent experimental units**; no multiple-comparison claim may replace this limitation. The scorer reports exact group-wise sign-flip values and Holm-adjusted eight-way family values; its intervals are descriptive only. Image-bearing LoCoMo turns remain text-only source frames here; no multimodal evidence sufficiency follows.

## Physical research protocol

1. An independent **source publisher** verifies the unchanged original corpus with `memory_retrieval_data.load_source`, then emits **only** `turns` and public `queries`. Gold answer/evidence/category is omitted. This producer has access to original annotations; the trained workers and sealing worker must **not** receive the original file. Keep public projections outside Git because they reproduce licensed conversation content.
2. A plan-freezing worker reads the *previously sealed* four-arm parent `plan.json` and public projection, binds exact Reader/tokenizer/prompt artifacts and source/forget frontiers, and writes a **create-only fsynced** new nine-arm plan. It cannot be regenerated after a prediction by overwriting its file.
3. A model/training worker executes all nine arms under pinned identities, with pre-evaluation artifact manifests. Train only on declared development source families; calibrate only on calibration families. Use the **same Reader and decode configuration** in every arm, measure real forwards, RSS, wall time, model residency, and Reader token counts. All rows must include exact model, request and evidence bindings. The protocol does **not** implement the real Dense/Graph/Head/Router/Split models for you.
4. A gold-blind sealing worker verifies the **full nine × question census**, each full reconstructed source frame, support-source scopes, budgets, artifact file bytes, and per-arm mechanism receipts. It rejects missing attempts, unseen evidence, duplicate keys, non-finite values, stale forget frontiers, forged context, silent model unavailability and incomplete physical mechanisms. A matching SHA-256 proves identity, **not signer independence** or truthful execution counters.
5. An **independent scorer** first verifies that the seal matches the unmodified plan, attempts and artifact inventory, then opens original gold and recomputes support outcomes from source IDs. Only this step sees categories and gold. The output retains unavailable/adversarial/unresolved attempts in the census.
6. A future external admission reviewer reexecutes representative Reader/model forwards and recomputes measured resource/cost, verifies source withdrawal/correction and DAG lineage, performs blinded semantic answer/citation adjudication and collects genuinely new chronological cohorts. **Absent these the only decision is `HOLD_NO_GO`.**

### CLI

Execute from `qa/stem-bakeoff` with Python 3.11+. All output paths must not exist (create-only). The real source can be provided via a private, license-compliant local path.

```sh
python3 memory_nine_arm_acceptance.py project \
  --original "$ORIGINAL_LOCOMO" --output "$RUN/public.json"

python3 memory_nine_arm_acceptance.py freeze \
  --parent-plan evidence/20261022-locomo-memory-retrieval/plan.json \
  --public "$RUN/public.json" \
  --reader "$READER_SHA256" --tokenizer "$TOKENIZER_SHA256" \
  --prompt "$PROMPT_SHA256" \
  --source-frontier "$SOURCE_FRONTIER_SHA256" \
  --forget-frontier "$FORGET_FRONTIER_SHA256" \
  --output "$RUN/plan.json"

# External model workers must create a complete, real:
#   $RUN/artifacts.json + $RUN/artifacts/ + $RUN/attempts.jsonl
# and preserve all nine arm/source/Reader resource identities.

python3 memory_nine_arm_acceptance.py seal \
  --plan "$RUN/plan.json" --public "$RUN/public.json" \
  --manifests "$RUN/artifacts.json" --artifact-root "$RUN/artifacts" \
  --attempts "$RUN/attempts.jsonl" --output "$RUN/seal.json"

# Run only in the independent, authorized gold-scoring environment.
python3 memory_nine_arm_acceptance.py score \
  --plan "$RUN/plan.json" --public "$RUN/public.json" \
  --manifests "$RUN/artifacts.json" --artifact-root "$RUN/artifacts" \
  --attempts "$RUN/attempts.jsonl" --sealed "$RUN/seal.json" \
  --original "$ORIGINAL_LOCOMO" --output "$RUN/report.json"
```

Manifest `schema=hepta.memory-nine-arm-artifacts.v1` contains `plan_sha256` and precisely nine `arms` entries. Each arm must bind `model_artifact_sha256 = SHA256(canonical(files))`, original physical `files=[{path,sha256,bytes}]`, `shared_encoder_sha256`, its disjoint `training_groups`/`calibration_groups`, positive *actual* training steps for E–I, actual Router training steps for G–I, graph training steps for H–I and executed split/merge for I. The physical inventory SHA is **not a signature**. Any attempt to count a proposal as an applied topology, to use a teacher fake as an original model, or to supply fabricated resource numbers must be rejected by an independent later reviewer.

Attempt `schema=hepta.memory-nine-arm-prediction.v1` binds the nine-arm `plan_sha256`, `arm`, `query_id`, `group`, `model_artifact_sha256`, `reader_artifact_sha256`, `reader_request_digest`, source/forget digests, `selected_ids`, full `context_sha256`, `context_bytes`, `status` (`accepted`, `abstained`, `unavailable`), raw `answer` and integral `runtime` counters. The request binding is `SHA256(canonical({"domain":"hepta.memory-nine-arm-reader-request.v1","query_id":...,"question":...,"context_sha256":...,"reader":...,"tokenizer":...,"prompt":...}))`. Row data must be JSONL UTF-8 with one final newline per row. `runtime` contains all exact fields in `RUNTIME_KEYS`. Do not use an invented output token count: it must come from the actual Reader. No hidden fallback to previously seen evaluation answers is allowed.

## Acceptance gates and unresolved blockers

| Gate | Closure condition | Current status |
| --- | --- | --- |
| S0 — protocol integrity | Pinned source, plan, full A–I ledger, replayable physical model artifacts, sealed independent scorer | **Implemented validator/test candidate; real 9-arm run missing** |
| S1 — strongest controls | Genuine Dense+BM25+Reranker (B) and Graph (C) run against same tasks/Reader | **OPEN** |
| S2 — local memory learning | E/F real trained weights, independent replay and stronger nearest-neighbor controls | **OPEN** |
| S3 — learned network | G/H trained sparse Router and Meta-Graph outperform fixed/static counterparts with measured cost | **OPEN** |
| S4 — structural benefit | I real split/merge and stable gain vs equal-budget static specialists, no regression | **OPEN** |
| S5 — quality and reliability | Independent semantic answer correctness, source citation entailment, calibrated abstention, multi-hop, forget/rebuild | **OPEN** |
| S6 — external validity | Future windows, independent source families and hosts, power and confidence, total cost | **OPEN** |
| S7 — admission | Exact-head required CI, external trust/replay/FinalUse, no security waivers | **OPEN** |

**No algorithmic superiority or production release** can be inferred from a passing schema/unit test. The default adjudicator intentionally **never sets `superiority_established=true`**, because its observable support-ID recall is insufficient. The six existing test conversation groups and prior model studies cannot close S5/S6 by relabeling. Promotion requires a separate authenticated evaluator and a genuinely new preregistered heldout cohort; any failed comparison remains a scientific negative, not a code blocker to be bypassed.

## Focused tests

```sh
python3 -m unittest discover -s qa/stem-bakeoff \
  -p 'test_memory_nine_arm_acceptance.py' -v
```

These verify fixture-only physical-artifact byte custody, a full 9-arm admission example, create-only sealing and score `HOLD_NO_GO`, as well as adversarial missing/duplicate rows, source mismatch, Reader drift, forged context, fake B/C forwards, missing Head/Router/Graph updates, split/merge omission, heldout-source leakage, mutable bytes, artifact path escapes, postseal tampering and duplicate JSON keys. Fixtures **do not** certify physical original pretrained forwards.

Run the owning standard CI, full exact-source architecture and security workflows independently. No test skip, waiver, historical-green transfer or main activation is authorized.
