# Actual code-solver preparation and local qualification

The previous retrieval proposer selected a command from teaching records. The
new solver uses a pinned code-generation model to propose implementation edits,
executes the unchanged task gates, and passes bounded real diagnostics into its
next proposal. Both registered arms use that same edit and task interface.

The registered development recipe contains two already exposed task families,
Ruff and codec, with no-history and BM25/code/path retrieval arms. It allows up
to three model calls per trajectory and retains every rejected proposal. The
official Qwen2.5-Coder-1.5B-Instruct Q4_K_M GGUF, llama-cpp-python source release,
generation settings and qualification boundaries are pinned in the solver
directory. The actual hosted protocol must be frozen before the first model
load; this preparation document does not claim a hosted run occurred.

## Local evidence before final formatting

- 18/18 pure unit checks passed, including extra-source/symlink refusal,
  qualification/runtime binding, actual diagnostic feedback, late model-byte
  drift invalidation and cost recovery after an interrupted model call.
- Real metadata admission accepted both existing independently exercised task
  fixtures and their exact runtime/qualification receipts. That check consumed
  the frozen model-input copy and ran no model or task subprocess.
- Pinned Ruff transformed the original failing source into the exact previously
  qualified `bb1509df…` control. The result is explicitly recorded as a generated
  control; it is not incorrectly attributed to Git's different `337403ea…` bytes.

`local-unit-result.json`, `local-unit-source.json`, `local-unit-output.txt`,
`real-admission.json` and `ruff-control-generation.json` retain these observations.
The source pins describe executed pre-format bytes; the publication bridge
records any formatting-only differences before remote execution.

Any model result must report task success separately from workflow/process
success. Runtime or integrity failure stops the study, preserves observed token
costs and leaves registered unexecuted denominators visible. The 128-MiB retained
size is an operation-boundary stop threshold, not a hard aggregate filesystem
quota. Direct-process and nested-child limits do not establish a whole-tree
budget. Generated candidate Python remains within the trusted-code boundary,
including no qualified runtime isolation from known repair code.

Independent future cases remain zero. This two-task development design does not
qualify a strong retrieval baseline, prove memory superiority, compare all five
capacity arms or close the general memory-system research gates.
