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
2. **The workflow remains on a research branch**, so GitHub cannot activate
   branch-only `workflow_dispatch` (GitHub requires default-branch registration).
   Instead, the operator commits the create-only literal file
   `qualification/e2-original-beans/PINNED_ORIGINAL_ARCHIVES.json` on this
   research branch **after** checking the completed origin run and pinning
   each numeric artifact ID and ZIP byte SHA. Its canonical JSON schema is:

   ```json
   {
     "schema":"hepta.e2.operator-pinned-natural-beans-archives.v1",
     "original_run_id":38680856403,
     "original_source_sha":"927bf53b184c3947db17a129834046c5f03add04",
     "artifacts":{
       "source":{"id":123,"sha256":"<exact 64 lowercase hex>"},
       "producer":{"id":456,"sha256":"<exact 64 lowercase hex>"},
       "withheld":{"id":789,"sha256":"<exact 64 lowercase hex>"},
       "independent":{"id":1011,"sha256":"<exact 64 lowercase hex>"}
     },
     "stem_selected":false,"production_accepted":false,"authority":"DENY_ALL"
   }
   ```

   Values above are **illustrative, not real artifact IDs or usable pins**.
   The activated file must use compact sorted-key canonical JSON with a final
   newline, all four actual roles, unique IDs and real SHA-256; the parser
   rejects missing/phony values. **No such activated file is committed now**.
3. On each ordinary research-branch push, the first job executes only
   contract tests. A separate intake job detects the operator's exact manifest.
   If absent it explicitly **skips physical replay**, not PASS; if malformed it
   fails closed. Only when present and valid does the two-job chain download
   the exact source and producer, then seal the label-blind Ridge. This uploads
   only a small research checkpoint/prediction pair, no raw images or weights.
4. The next separate job downloads all four ZIPs and their original SHA-pins,
   verifies the same successful run/head and source/target bytes, and recomputes
   model weights by independent SVD before opening TEST labels. Only a complete
   pass writes `readout.json`. Secrets are never printed or uploaded; the
   GitHub token has `actions:read` and `contents:read` only.
5. The presence of this workflow (without the operator manifest) or passing
   source-tests cannot claim an original natural-image task result. For local
   CLI reproduction use `e2_beans_original_artifact_fetch.py` and
   `e2_beans_original_replay.py` after obtaining all four original ZIP pins.

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
