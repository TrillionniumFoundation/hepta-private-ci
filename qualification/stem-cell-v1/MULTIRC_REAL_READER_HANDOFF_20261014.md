# Human-annotated MultiRC multi-question Reader — handoff, 2026-10-14

Source parent: `cb7c5e4165adeb91b737c6ebdcb35cce4fdaa9ea` (Draft #1962).
Tested code commit: `2d4772c7951a38c88e565fdb9eb9136b99aa10ff` (Draft #1970).
Research-only, no main merge, production installation or change to existing trained models.

## Why
The prior conditional evidence Reader passed a synthetic two-fact panel. This
follow-up can use human-annotated *MultiRC* train and validation source passages,
with two different question IDs and one candidate answer per question. It is a
small, label-blind selection of the MultiRC data, **not the full official metric
or benchmark ranking**.

Public dataset repository: `aps/super_glue`, exact source revision
`4e14482c58d790d467ecfb29b6790e1917bf8756`. The read-only material
operator pins train/validation Parquet bytes and uses a preregistered, label-blind
selection (8 training and 4 heldout passages, two questions and the lowest
candidate answer ID per selected question). Duplicated normalized evidence
content is not treated as multiple source groups, and train/validation overlap
is rejected. Labels are only available to the separate material-owner/
postprediction evaluator interface, not to model fitting.

## Real model experiment to be executed on hosted CI
- Load one frozen locally pinned ModernBERT safetensors checkpoint with complete
  tensor materialization and shared embedding checks.
- Encode a passage once into full token-level evidence states. Two different
  question/answer candidates each receive separately charged lightweight query
  embeddings from that same checkpoint embedding table, **not two independent
  149M-parameter Encoder forwards**.
- Train four separate same-parameter Readers: query-conditioned cross-attention,
  mean-pool/query fusion, question-only (no evidence), and passage-only (no query).
  Keep one retained normal FP32 evidence buffer per paragraph, rather than
  doubling it for each question.
- All Reader fitting must finish before opening the blind validation input.
  Frozen weights and predictions are content-sealed before separately retained
  annotated labels can be used for scoring. Failures have FAILED receipts, not
  fabricated successful scores.
- Report raw accuracy, Brier, majority baseline, per-passage counts and paired
  recovered/lost questions; repeated questions from one passage are not
  independent data points. Track observable Encoder/query/projection/Reader
  arithmetic separately; Python work, full memory/energy and publication
  costs are not made zero.

## Verification actually obtained
22 targeted genuine-PyTorch source tests passed. Twice the local source-slice
completed 577 distinct source tests, no failures/errors/skips/discovery errors
and identical test inventories. All five Git blob SHAs exactly match locally
tested files; Python compileall and three-job workflow YAML parse passed.
The original upstream 555-test source slice is not an authoritative full
checked-out remote Git tree. Hosted tests on their exact ref must be read
separately, and no hosted pass is claimed while queued.

Use `run_checked_tests.py --pattern test_multirc_real_study.py` for the CPU
source suite and `--pattern hf_multirc_checks.py` only under the pinned installed
Transformers job. Public CI downloads pinned train/validation Parquet files
and public ModernBERT weights, then calls `multirc_reader_study.py prepare`,
`run` and `score` in that order. Hosted artifacts deliberately omit
raw passages, raw labels and model weights.

## Limits
The public dataset lists license "other"; independent production licensing
and provenance approval remain absent. Pretraining contamination, source
independence and the true authenticity of the external scoring role have not
been established. The local runtime has no installed Transformers/pyarrow, so
the actual pretrained MultiRC accuracy is **not available** in this commit.
No statistical superiority, NDU/System2 net gain, longitudinal learning,
native service/energy optimization, multimodal generation, 1024/4096-scale
or 10T/100T equivalence has been demonstrated.
