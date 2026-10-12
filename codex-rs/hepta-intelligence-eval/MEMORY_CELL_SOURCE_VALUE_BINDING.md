# Source-only writer: exact-value-binding diagnosis

This is a historical, source-bound diagnostic, not a new memory training run.

## Frozen original model observation

- Research model: pinned `Qwen/Qwen2.5-3B-Instruct` (the repo's existing Qwen tier).
- Generating code: `8ac9692a86a2727ea42e699d9da42dd0e67087bf`.
- Real model workflow: `38191092672`, job `114626264255` succeeded; the
  *overall workflow* failed because unrelated Python formatting was not clean.
- Original artifact: `11723225786`, archive SHA256
  `79c7de0d4f61aa2d4dec6c337b57aa6e6fce28c9567df5bd3cadbdbae714ba19`.
- Source-only writer: 128 updates, 27,890 input tokens and 1,096 supervised
  tokens. The one-step full/sparse Qwen/PEFT comparison had equal loss, gradients
  and parameter update; these are NOT end-to-end learning gains.
- Seven-arm task results: hybrid 4/8, deterministic organization 8/8,
  organization plus memory LoRA 8/8, initial read policy 5/8, learned read
  policy 8/8, empty-context frozen 0/8, memory LoRA alone 0/8.
- Original in-sample *source-only* probes: 16 training questions, 32 real
  outputs; both base and LoRA attained 0/16 exact targets. The frozen base
  refused all 16. The LoRA produced 16 syntactically plausible identifiers,
  none equal to **any of the 88 source-derived training targets**. This does
  not prove absence from every raw source document, nor from model pretraining.
- Teacher-forced target NLL decreased for all 8 tested scopes under both source
  question wordings, yet exact free-generation task success did not increase.
  The existing negative log-likelihood and decoder probes retain their own
  source identity. No result from one method is attributed to another.

## What the new consumer proves

`source_value_binding_audit.py` opens an immutable READY snapshot, the frozen
source recall plan, its original 32 model answers and the original diagnostic
report. It checks four bytes-level SHA256 pins, question and reader identity,
pretraining source ancestry, actual training schedule/optimizer visit counts,
zero actual delivered evidence, complete base-vs-adapter answers, and original
exact-target/failure numerators. New read-only categories separate exact source
values, refusal, **same-scope wrong relation**, cross-scope value, a plausible
identifier absent from source *training targets*, unsupported citations and
execution failures. No answer is generated or repaired; wrong-typed content
and incomplete outcomes cannot become wins.

An independent GitHub Actions *process* reruns the auditor against the pinned
historical archive, without starting the pretrained model or modifying
trained weights. This process is **not** an independent human fact/citation
reviewer, and its frozen answers remain previously exposed development data.

## Next scientifically meaningful change

The observed failure is **identifier morphology without correct value binding**.
Before increasing adapter steps, test independently which mechanism limits
performance: teacher-forced candidate separation, constrained candidate
ranking with the same candidate vocabulary for both base and LoRA, versus
unconstrained generation; train/test separation by original source family;
random identifiers versus genuinely compositional relations and procedures.

If the candidate vocabulary comes from original source documents, count its
construction, delivery and storage as a non-parametric retrieval/lexicon control,
not a pure parameter-memory gain. Compare with deterministic event organization
and strong hybrid RAG on exactly the same reader and tools. The current writer's
128-step in-sample data **cannot** establish independent generalization.

Always keep `semantic_citation_precision=null`, `production_accepted=false`,
no unearned N_eff or future windows, and existing owner/fleet/revocation gates.
