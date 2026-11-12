# Final format order after the 39 + 10 protection/QA integration

Status: **read-only preparation; no formatter, H task, Cargo or qualification gate executed here**. This note does not extend the currently running V5 maintenance attempt or approve another attempt by itself.

## Why one final format invocation is required

The pinned repository [AGENTS.md](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/86dd56a930277e0d1aef3e475e35c2b5d60b43b7/AGENTS.md), blob `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a`, requires `just fmt` after finishing code changes anywhere in the repository. The 39 existing protection migrations, 10 new protection rows and associated QA/allowlist integration occur after the current maintenance formatter has produced the Rust bytes they protect. Therefore the earlier format result alone does not cover the last integrated source state.

The minimal remaining format command is the already selected original command:

```text
just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f
```

Use the original **900-second format-command limit** and original recorder with the actual current source/environment/process preconditions. This is a separate recorded final-format invocation after integration, not a larger timeout for V5 and not another `just fix` or Cargo test pass. Do not replay a whole maintenance wrapper merely to get its fmt stage, because that would also repeat fix.

## What the unchanged formatter actually owns

The pinned [scripts/format.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/86dd56a930277e0d1aef3e475e35c2b5d60b43b7/scripts/format.py), blob `d4eabe70b68605933240e9129245f7f4cccbde5d`, provides the actual selection:

| Function / input | Actual behavior |
|---|---|
| `changed_paths(base)` | Resolves the exact base commit, reads the complete Git diff from that base plus untracked nonignored paths, and keeps supported existing files/config removals. It does not need a merge-base or complete ancestor history. |
| `scoped_formatter_groups` and `rust_configuration_scope` | Select changed Rust files, with Rust configuration changes expanding only their subtree. Rust is still selected from the whole fixed-base diff even when the latest addition is non-Rust. |
| `rust_file_command` | Uses the owning manifest/toolchain, edition and original `imports_granularity=Item,skip_children=true`; no behavior tests. |
| `python_scripts_formatter_group` | Runs the original frozen scripts-project UV/Ruff formatter for selected `.py/.pyi` files under `scripts/` and `.github/`. |
| `CALLERS.toml` | No general TOML formatter exists in this dispatcher; this filename is not a Ruff configuration trigger. |
| `qa/b4-no-bypass/*.py` | Outside both declared Python formatting roots. The current `just fmt` dispatcher does not send these QA files to Ruff. |
| Blob-size allowlist text and workflow YAML | Not formatting targets of the current dispatcher. Do not claim those bytes were automatically reformatted. |

Consequently, the final command is required by the repository's workflow and may revisit the earlier Rust/scripts changes. It must not be advertised as an automatic format check of the new QA directory, CALLERS or allowlist. This note proposes no formatter-scope expansion, direct extra Ruff command, optional test or new budget.

## Minimal exact sequence

1. Let the one current V5 maintenance attempt finish. Preserve its original fix/fmt outcomes and every real Rust or script postimage, including failure/Unknown outcomes.
2. ordinary_path remains the sole writer for the 39 + 10 protection changes, associated QA/workflow/allowlist work. Derive exact literals from the actually formatted Rust; preserve old protections and case registrations.
3. Integrate that reviewed non-Rust preparation with the actual Rust postimages into one candidate source. Hold source mutation while the final format command runs.
4. Record one original `just fmt --base c0f…` with 900 seconds, retaining command stdout/stderr/result, complete before/after source observations and actual postimages. Reuse restored tools through their actual identities; do not re-download or alter the dependencies.
5. If the formatter succeeds and the protected Rust/other source dependencies have not changed, the synchronized protection literals can be retained. Freeze the final canonical commit/tree and actual clean materialization only after reviewing any formatting changes.
6. If it changes protected Rust or an exact dependency used by a source guard, **stop final freeze**. Synchronize the affected literals/QA/allowlist against those actual bytes, preserving semantics; review the resulting source before any claim. Do not silently keep old markers, extend the failed command budget, add Cargo tests, or treat an unexecuted follow-up as PASS.
7. Once the final source is frozen, execute the already authorized original exact-source qualification plan with its original selections and limits. This is the separately requested final-version qualification; this note adds no Rust test invocation. The generic AGENTS advice against optional test reruns after fix/fmt is not a reason to inherit results from an older source or to add redundant tests here.

The final library evaluator count is independently corrected in PLAN V2: the old **163** is only the c0f historical observation. Run the same complete unfiltered library command; derive new executed/pass/fail/skip counts from fresh JUnit and the actual final-source library inventory, while preserving the four required regression names and the 3600-second budget.
