# Recorded chat evidence admission — HOLD_NO_GO

The original #6099 arithmetic script used Python `assert`, hard-coded host paths,
and independently grouped starts and completions without checking their run IDs
or adjacency. Thus its grouped checks accept a reordered journal or a mixed-run
journal with consistent replacement hashes. Python `-O` removes its assertions.
The original evidence and that historical script are preserved unchanged.

`chat_evidence_audit.py` adds a portable standard-library, read-only admission
command. It explicitly raises errors under normal Python and `python -O`, rejects
duplicate JSON keys and non-finite numbers, and checks every start/completion
pair, exact sequence, common run ID, terminal record, row types, frozen labels,
parser outputs, summary and denominator. A self-consistent replacement hash is
not accepted as the frozen source binding: all six original source hashes and
the complete recorded configuration, runtime, prompt-token and model-witness
objects are anchored to the original archive.

Original model execution source: `4669280bd92804e6b5357ec0d8a27197858a5b6a`, tree
`d78b935a2f5abe1273dced958460c7a3e23ddea6`. This addition is stacked only on
#6099 evidence commit `8187f91331dd2b1b37c65116eedeed2b1b3941e5`.

## Observed verification

- Exact recorded RESULT / PREEXECUTION / ROWS and six source files were read from
  GitHub and rechecked locally. All 24 rows and all 49 journal events pass:
  **12 valid, 6 correct, zero first-token EOS**. Invalid answers remain in the
  primary 24-task denominator. No label, threshold, prompt or parser was tuned.
- Fifteen tests passed normally, and the same fifteen passed with `python -O`.
  This is repeated software testing, not 30 independent experiments. Cases cover
  mixed-run/hash-consistent journals, cross-pair reordering, Python bool/int
  aliasing, non-finite time, nested duplicate keys, truncation and semantic
  source/configuration/runtime/model/prompt-witness substitutions.
- Separate same-session review reproduced source/configuration substitution
  counterexamples before repair and confirmed rejection afterward. This is not
  external custody or a second model experiment.
- Original local logs, process resource observations, input/result hashes and
  source hashes are in `evidence/chat-evidence-admission-20261112/`. An initial
  `/usr/bin/time` launch failed because the executable is unavailable: zero
  tests ran; those failure logs remain. Successful tests used Python stdlib
  process resource accounting. These costs cover test processes only.
- `ruff check` passed. `just fmt` was attempted and returned `no justfile found`
  in this sparse source set; repository formatting is not claimed. New exact-head
  Actions results must be read separately before claiming hosted qualification.

Reproduce from this directory:

```sh
python -m unittest test_chat_evidence_audit -v
python -O -m unittest test_chat_evidence_audit -v
python chat_evidence_audit.py --source-dir . \
  --evidence-dir chat-native-cpu-evidence-20261112/execution
```

## Limits

This checks recorded bytes and arithmetic. It executes **zero new model
inferences** and does not re-decode tokens or rehash model files on ai395; these
fields remain `NOT_RUN`. Anchored model and token arrays are historical
witnesses, not independent proof that the model produced them. The original
public tasks remain exposed protocol diagnostics, never future confirmation.
Independent calibration, independently held future sources and old-task
retention remain **MISSING**. No HPCA scheduling gain, energy saving, Owner
permission, adoption, deployment or production qualification is established.
