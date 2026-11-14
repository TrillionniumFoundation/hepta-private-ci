# HPCA public chat-wrapper output-contract diagnosis — HOLD_NO_GO

**Precommit before inference.** This independent branch is stacked on #6049
at exact source \`48d9f4776d1fa5b6aad42760f2d4f4a8b9a9770a\` and
does not modify or re-run its frozen 24/24 bare-prompt EOS reference.
The distinct #6044 real experiment recorded 216/216 EOS across nine
conditions on the same 24 exposed questions. Neither proves universal model incapacity.

## Single prospective arm
Run only the original **base model**, zero adapters and no training.
Take exactly \`question.strip() + "\\nAnswer:"\` from the frozen 24-task
roster, without changing that content, and wrap it in one tokenizer-native
user chat message with \`add_generation_prompt=True\`. No system message,
few-shot examples, prompt/label search, threshold or post-hoc adjustment.
Use the original official model revision and weight/config/tokenizer digests,
same CPU/dtype/4 threads, neutral greedy 8-token generation, and a
strict leading whole-word YES/NO parse. Invalid outputs count as incorrect.

This tests whether input-format incompatibility can explain observed EOS;
changing chat tokens changes model context, so this is **not** an
information-matched causal estimate of HPCA learning or a revised OOD result.

Source/model hashes, exact prompt IDs and runtime are frozen in PREEXECUTION.
Each attempted and completed row is fsynced; all 24 are required for RESULT.
Measured full-process wall/CPU/RSS and model download are reported separately
from unmeasured queue/CI/energy/Owner costs. No independent B, old-task
retention, Agentd Adopt/NoUpdate/C, cold recovery or Core×NDU factorial.
Every result remains **DENY_ALL / HOLD_NO_GO** regardless of test success.
