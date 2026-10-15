# Natural Beans: complete pinned original-ZIP replay + independent SVD oracle

**Research only — Draft / SHADOW_ONLY / DENY_ALL, no model, FinalUse or promotion authority.**

This is the missing **physical-archive replay execution path**, not a new synthetic
model, another downstream label owner, or a claim that the queued natural-image
pretrained inference has already produced outputs.

## Original source boundary

- Reference source is the exact historical Beans original implementation commit
  `927bf53b184c3947db17a129834046c5f03add04`, PR #2189, Actions
  `38680856403`. The replay deliberately rejects any other `head_sha`, even if
  the branch name, report fields and apparent class metrics agree.
- Only after that run reports **completed/success**, an independent operator pins
  **four** original GitHub Actions artifact IDs *and their full original ZIP
  SHA-256s*: `source`, `producer`, `withheld`, `independent`.
- GitHub Actions artifact *names* alone are **not** stable identifiers; both
  exact numeric ID and byte hash are required. The fetcher rejects a mixed run,
  source revision drift, expired/missing/renamed artifacts, duplicate IDs,
  unsafe non-HTTPS redirects, redirected bearer credentials and changed ZIPs.
  The fetcher accepts no arbitrary user URLs. Without pinned archives it fails.
- Phase A runner physically downloads **only source and producer ZIPs**. Neither
  withheld label ZIP nor the independent original score is downloaded to the
  train-only job. It fits a frozen-DINO 384D → 3-class Ridge with fixed alpha
  0.1, using only 36 original training leaves, saves 1,155 parameters, and
  predicts all 24 original TEST feature vectors. Original DINO/Granite model
  weights and image forwards are **reused**, never downloaded or rerun here.
  The separate process outputs immutable `probe_model.json` and
  `probe_predictions.json` with pinned byte hashes.
- Phase B is a different Actions job/process. It receives all four original
  byte-pinned artifacts and the immutable seal, first recomputes the 36-example
  Ridge via a numerically independent **thin SVD** (the producer uses a dual
  normal-equation solver), and checks all 24 original future predictions.
  Next, it runs the existing strict original four-ZIP archive auditor and
  independent label-bearing reviewer. Missing targets or inconsistent original
  scorer bytes fail closed; its output includes paired Bridge/vision-Ridge/
  frozen-prototype outcomes and negative scientific admission flags.

## Running

1. Original Beans physical run must complete, with all four original artifact
   SHA-256s and IDs independently recorded. The archive run was queued at the
   time of this implementation; no natural-image score is inferred here.
2. Dispatch `hepta-e2-beans-pinned-original-replay.yml` with original run ID and
   **all four immutable ID/SHA pairs**. The first, label-blind job downloads
   only `source.zip` and `producer.zip` and uploads an approved *small sealed
   model/probability research artifact, not raw images/weights*.
3. The scoring job downloads all four ZIPs, verifies source identity and
   SHA-256 independently, rereads the immutable Ridge seal and produces the
   independent `readout.json` only upon complete success. Secrets are never
   printed or uploaded; `GITHUB_TOKEN` needs `actions:read` and `contents:read`.
4. The workflow also runs mechanism/negative tests on ordinary branch pushes,
   but **those tests never count as a real natural-image execution**. For local
   direct CLI reproduction, use the two scripts `e2_beans_original_artifact_fetch.py`
   and `e2_beans_original_replay.py` with their `--help` arguments.

## Scientific qualifications not supplied

- The label split is retrospective Beans TRAIN/TEST, **not** three source-
  independent natural future windows or plant/farm identity separation.
- 24 examples give high statistical uncertainty; existing independent paired
  McNemar/Holm scores must be interpreted as exploratory and cannot choose Stem.
- Class descriptions come from three class caption templates, **not** evidence
  of general multimodal language reasoning or question-conditioned grounding.
- Frozen visual Ridge is *supervised* using the original class labels and has
  fewer parameters than the 384×384 crossmodal Ridge; comparison does **not**
  equalize compute or training degrees of freedom.
- Zip authentication is byte consistency plus GitHub-run association, **not**
  a publisher signature, independent physical execution attestation or
  independent natural-image annotation audit.
- Five-arm Text/OCR/native EmbeddingGemma comparison, target host RSS/energy/
  p95/p99, memory-cell downstream task success, NDU, negative transfer,
  blocking-ci, and every signed FinalUse/revocation prerequisite remain open.

**Disposition: `production_accepted=false`, `stem_selected=false`, `DENY_ALL`.**
