# Reader evidence context and digest bindings

Observed and validated on 2026-10-21 UTC. This change is an isolated child of
`research/real-reader-intake-p4-20261017`, commit
`f191cd081ba16fed8827a18093b5a5b39e9a36cd` (PR #2714).

## Defect and behavior

The runtime and calibration adapters accepted caller context that contradicted
the payload's declared candidate or source split. The runtime adapter also let
a caller replace a reported checkpoint digest, and used a truthiness fallback
that could hide conflicting or malformed runtime digest aliases.

The adapters now reject a present candidate or split unless it is a string
equal to the caller's context. A supplied checkpoint digest must be a valid
SHA256 value and must match any non-null reported checkpoint. Each non-null
runtime digest alias is validated independently; when both aliases appear,
their values must agree, including nulls.

Existing callers may still supply context when the payload omits it, and may
join a previously absent or null checkpoint. Matching strings or a supplied
join do not authenticate evidence. Valid legacy aliases retain the original
serialized receipt and digest. Unknown evidence remains incomplete; the
`DENY_ALL` and `next_snapshot_only` boundaries remain in force.

## Validation

| Check | Observed result |
| --- | --- |
| Original source with initial context negative controls | 36 failing assertions/subtests across 11 test methods |
| Initial context fix with additional alias controls | 14 failing assertions/subtests across 16 test methods |
| Final complete qualification suite | 125 tests passed; zero failures, errors, or skips |
| Independent Reader suite | 40 tests passed |
| Independent extra adversarial and compatibility cases | 158 cases passed |
| Ruff 0.15.13 lint (`E,F,I`) | Passed on both changed Python files |
| Ruff format check | Both changed Python files already formatted |
| Parent checkout `just fmt` | Exit 0; qualification Python is outside that formatter's scope |
| Exact-source verification | All 25 unchanged qualification files match the parent Git blobs |

The independent extra cases compare original valid outputs and receipt
digests, exercise conflicting and malformed fields, and check that input
payloads are not mutated. Counts of failed assertions above are not counts of
distinct test methods. These are synthetic contract tests, not model calls.

Reproduce the complete Python suite from the repository root:

```sh
python3 -m unittest discover -s qualification/neuron-shared-encoder/tests -p 'test_*.py' -v
ruff check --select E,F,I qualification/neuron-shared-encoder/neuron_shared_encoder/reader_runtime_receipt.py qualification/neuron-shared-encoder/tests/test_reader_receipt_context_bindings.py
ruff format --check qualification/neuron-shared-encoder/neuron_shared_encoder/reader_runtime_receipt.py qualification/neuron-shared-encoder/tests/test_reader_receipt_context_bindings.py
```

| File | Git blob | SHA256 |
| --- | --- | --- |
| `neuron_shared_encoder/reader_runtime_receipt.py` | `585c77d133f98bb29964c6ce71670f2af7676b33` | `1d2b1010980a2d0d521c81a7761423cbcd32fa50c30dc3d33f62197591837019` |
| `tests/test_reader_receipt_context_bindings.py` | `a981f032581d2439ee3e8ff55291c3f2ec2ca884` | `a83ae9200ebc91dec3c9503d53cbec4ecab2cafc629970f00af86669ff1e7f7a` |

## Qualification limits

The patch corrects research receipt integrity. It does not establish model
quality, independent source provenance, production authorization, training,
native platform qualification, or a successful new inference experiment.
Research posture remains `SHADOW_ONLY / DENY_ALL / NO_GO`. The parent research
PR and this child remain draft pending their own evidence and integration
gates. Remote CI results must be associated with the actual pushed commit.
