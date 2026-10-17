# P11 — Repair actual P8 model-load failure without replacing original P1/P2 dependencies

**DRAFT / RESEARCH_ONLY / DENY_ALL / NO MAIN MERGE / NO MODEL PROMOTION.**

## Original failure observed, not a fabricated benchmark

P8 [run 39019492161](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39019492161), job `117375601553`, failed at `2026-10-17T11:41:20Z` with:

```text
ModuleNotFoundError: No module named 'portfolio'
```

The original, SHA-pinned source selection completed, but no P8 Qwen inference or postseal outcome finished. The traceback leads from `physical_online_p8/online.py` to the immutable `physical_online_p2/physical_online.py`, which imports **the P1 `portfolio`** and **P2 `public_source`** using legacy bare names. P8 only added its own directory to Python's search path. P9 also names its **different** policy module `portfolio`, so a global search-path change cannot safely disambiguate P1/P9 modules.

P9 run `39021501950` had passed source-contract/original-source but its model job was still queued when this repair was written. P10's real P5 covariance/replay finding, including missing counterfactual support and no NDU superiority, is unchanged.

## Surgical source change

`physical_online_p8/online.py::old_model_loader()` now:

1. Resolves the expected **in-tree** P1 `token_portfolio_p1/portfolio.py`, P2 `physical_online_p2/public_source.py` and original P2 `physical_online.py` by their exact paths in the same checked-out commit.
2. Rejects missing/symlinked modules, unexpected cached module locations, malformed loaders and changed original Qwen checkpoint/profile identity.
3. Loads P1 and P2 original source using namespaced module identities. Only the historical worker receives a module-local `__import__` binding for its own bare `portfolio` and `public_source`; `sys.modules['portfolio']` and `sys.modules['public_source']` for every other caller remain untouched. This prevents P9's live policy from being substituted for P1 in Qwen's original worker.
4. Keeps P5's original pretrained Qwen3-0.6B loader, checkpoint SHA256, tokenizer SHA256, seed, sampling, prompt formats, output parser and raw receipt semantics unchanged. The repair has no authority/selection/effect operations and is not itself a model call.

Both existing P8/P9 research workflows now perform **genuine source-module import smoke checks during their cheap `source-contract` stage**, before model downloads. Both original independently paid online model and postseal steps remain present; no `blocking-ci` or independent evaluation is bypassed.

## Local reproducible source-only evidence

```bash
D=experiments/ndu_tree_fbsde_gates/merton/physical_online_p8
PYTHONPATH="$D" python -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
PYTHONPATH="$D" python -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
D=experiments/ndu_tree_fbsde_gates/merton/physical_online_p9
PYTHONPATH="$D" python -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
PYTHONPATH="$D" python -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
```

P11 adds five tests simulating legacy sibling dependencies, including P9 name collision, nested import, a missing module, frozen checkpoint drift, symlink refusal and failure/retry cleanup. Those fixtures are **not original P1/P2 code**; actual original source import conformance is verified by the new GitHub CI smoke commands against the exact PR checkout. Ordinary tests do not load weights or infer task quality. In this local execution environment, P9 source tests additionally used an explicitly local-only P2 Source compatibility fixture because the entire multigigabyte repository was not cloned. The compatibility fixture is **not committed** or claimed as original.

## Qualification boundary

- **Do not retroactively relabel P8 run `39019492161` as successful.** Its original Qwen calls and independent scoring did not occur.
- Successful preflight proves import resolution, not that a future model can be loaded/run within memory, time or resource limits; the new exact-head physical run must actually complete and separately score results.
- P9's submitted fixed-budget controls, P10's no-go, and the original 16-task P5 historical panel are not promoted or rewritten by this patch.
- `main`, production NDU/Neuron/World Model/FinalUse, selected artifacts and CI authority remain unchanged. All research checks and full protected `blocking-ci` retain their original meaning.
