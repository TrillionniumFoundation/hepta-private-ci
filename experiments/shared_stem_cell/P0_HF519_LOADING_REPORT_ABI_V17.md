# P0 V17: exact Transformers 5.19.0 loading report ABI — research / DENY_ALL

## Actual failure and upstream root cause

The actual E1 public CPU runs `38893928466` and `38897062717` completed
Granite97 and EmbeddingGemma2 text Encoder + Head executions, but mmBERT
failed before the whole-original-checkpoint byte proof with
`p0_mmbert_tied_load_contract_v15.Invalid: invalid unexpected collection`.
The original V15 loader accepted only `list`/`tuple` loading-info collections.

The **actual fixed upstream** [Transformers 5.19.0 loading_report.py](https://github.com/huggingface/transformers/blob/v5.19.0/src/transformers/utils/loading_report.py)
(Git object `8d7e71944fa9edc98d94a0601783b3390cd39cde`) defines
`LoadStateDictInfo` with `missing_keys`, `unexpected_keys` and
`mismatched_keys` as `set`; `error_msgs` is `list`. Its `to_dict()` returns
these container objects directly. Thus, even an **empty** `unexpected_keys`
set is incompatible with the former parser. The bounded `list/tuple/set/
frozenset` compatibility fix in #2495 handles this *structural* issue.

Crucial upstream omission: `LoadStateDictInfo.to_dict()` deliberately does
**not** export `conversion_errors` or `skipped_pp_keys`. An apparently clean
metadata report cannot alone certify absence of source conversion issues.
The existing original `verify_tied_pretrained_table()` and
`verify_complete_pretrained_state()` **must still** prove shared storage and
compare every serialized original checkpoint tensor byte before any Encoder
feature or model-selection receipt can be admitted. This additional probe
never loads the actual checkpoint, and cannot substitute for those checks.

## Actual implementation

- New `p0_hf519_loading_report_abi_v17.py` implements a bounded,
  **research-only** ABI/strict-contract test. The module itself is standard
  library only; its `main()` imports the **real pinned installed**
  `transformers.utils.loading_report.LoadStateDictInfo` and checks exact
  `transformers.__version__ == 5.19.0`, on both source and prospective merge
  runners, after `pip check` and before obtaining model weights.
- Verify actual upstream `to_dict()` fields and collection types; confirm
  that the existing original source/alias strict verifier refuses non-tied
  missing weights, unexpected saved keys, mismatched tensors and error
  messages, including when they are native `set` objects. Recognized tied
  aliases remain *provisional*, never an accepted pretrained model.
- Explicitly test that upstream's `conversion_errors` are omitted from the
  returned dictionary; record that gap without inventing weight verification.
- Capture only fixed field names and type strings, a bounded test count,
  pinned package version, and `DENY_ALL` flags. No tensor names, bytes,
  prompts, human labels, source paths, raw exception messages or model ranks.
  File creation is exclusive/create-only and fail-closed on error.
- The already existing strict P0 physical workflow executes **both** the
  stdlib regression and the real installed-upstream ABI inspection before
  the untouched original SHA/LFS acquisition, complete tied-table byte
  comparison and original CPU Encoder forward. Any failure returns nonzero
  and retains `DENY_ALL`.

## Verification and limits

Local isolated fixture regression: **12/12** source-only adversarial tests
normal and **12/12** under `python -O`; combined with the exact existing
V15.1 alias tests, **29/29** normal and **29/29** optimized. These local
checks use a standard-library dataclass faithfully shaped after upstream;
**the real Transformers wheel is NOT installed in the local environment**.
The actual pinned upstream ABI check is deliberately performed by the hosted
GitHub runner after installing the original fixed packages.

No pretrained physical mmBERT load/forward, four-model original-human
MultiRC score, future NDU utility, negative transfer, 4,096 Cell target
resources, independent signature, production model selection, `main` merge,
FinalUse or Cell Split authority is claimed.

**DRAFT / RESEARCH_ONLY / DENY_ALL.**
