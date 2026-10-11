# Opt-in completion-only source-write projection — research parity, not adoption

This change retains the registered source-only writer, precommitted source schedule, allowed source roots, frozen Qwen2.5-3B base reader, 128 update ceiling and 65,536 input-token ceiling. The default CLI remains `--loss-backend full` with the original model-owned loss. The experimental `--loss-backend supervised_positions` projects only logits at target-predicting positions; all prompt tokens still traverse every decoder layer, and their gradients are retained. It must fail closed on missing Qwen2/PEFT `logits_to_keep` support rather than silently fall back or change the target.

Keep `input_tokens`, `supervised_tokens`, `actual_projection_positions`, optimizer steps, tensor dtype, source ancestry and input/prompt digest distinct. Fewer vocabulary logits do NOT imply fewer decoder FLOPs, input tokens, model loads, total lifecycle costs, or improved answers.

The isolated staging branch `codex/memory-cell-source-loss-20261011` executed genuine Transformers 4.57.1 / PEFT 0.17.1 Qwen2 **random-weight** parity tests for FP32 and BF16, including three optimizer steps. A later hosted run performed the inherited **433 Python regression tests** and real writer-loop fixtures; all passed before mandatory Ruff formatting rejected three test files. The locked Ruff 0.15.13 formatter then produced exact AST-equivalent reviewed file bytes. Final exact-head CI must still finish; preceding execution cannot be relabelled as new pretrained task evidence.

- Initial pinned Qwen/PEFT parity: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38096801390 (tests passed; missing Ruff binary made the overall job fail).
- Writer + full regressions: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38097057912 (433 tests passed, format check failed on three files).
- AST-preserving formatter candidate: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38097412135 (passed).
- Latest staged confirmation: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38097490680 (must check actual terminal status).
- Seven-arm pretrained source write: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38097531656 (must check actual terminal status, never infer success from job creation).

The original fixed 108-source/16-scope corpus produces only eight final held-out tasks (two each of new fact, correction, composition and procedure). Test annotations must not influence writing, retrieval, runtime calibration or tool behavior. The organized and learned-policy baseline results in older runs remain controlled development evidence; do not reinterpret them as statistical superiority over an independently tuned strong RAG.

No independent future windows, signed semantic >=99% entailment, N_eff >=200, genuine retention guarantee, cross-host rollback, production authorization, or sampled production cost benefit was obtained here. `production_accepted=false` remains mandatory.
