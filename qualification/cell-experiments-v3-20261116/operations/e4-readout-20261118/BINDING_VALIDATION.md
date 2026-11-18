# Bind E4 readout to the frozen worker and unique calls

The previous reader could report `COMPLETE` after a worker binding was changed, two graph nodes reused one call while another call went unreferenced, or the selected answer fields were edited. The fixes bind the protocol, comparison and source inventory, check canonical node slots and the complete call-receipt directory sets, and derive the earliest successful answer (otherwise the last surviving answer) from the original nodes.

The reader also binds frozen model identities, contract and token budgets, task identities and per-group task coverage. The original pool class/source gates remain. Reused calls invalidate the observed cost lower bound; all incomplete runs retain null complete call/token totals. Prior failure and diagnostic costs remain a separate protocol-bound history and are not added to the new graph totals.

## Verification

- The unchanged reader at `ddf8ef8a721b1d0d8aa42b02b9c52f3bc1ab3c34` fails 22 adversarial subcases across the 12-method suite. The repaired reader passes all 12 methods with zero skips.
- Fixtures are explicitly synthetic receipt data. They test opposite success transitions, binding changes, duplicate calls with equal file counts, changed selections and answer hashes, slot order, task coverage, model identity and budgets. They execute no model or business verifier.
- Offline readback of the real earlier pool failure remains `INCOMPLETE`, with zero completed graphs and all six complete call/token fields null. The original archive is retained in #6679 and identified in the validation index.
- One unchanged real graph and its original receipts verify format compatibility: first success, then a format rejection, with the first answer selected. This partial snapshot remains `INCOMPLETE` and supplies no complete-run costs.
- The repository's original `just fmt` exits zero. Both final ASTs equal the tested ASTs; tests were not repeated for formatting.

`BINDING_VALIDATION_RAW.tar.gz` preserves the tested pre-format sources, original reader, execution intents/start/exit/logs, formatter receipt, offline readouts and their selected original inputs. Its `MANIFEST.json` gives every member's byte size and SHA256; all members were read back and checked. `BINDING_VALIDATION.json` binds that archive and the final source hashes.

## Reproduction

Run `python3 -I -B test_readout_binding.py` from this directory for the synthetic data suite. To reproduce the original red cases, extract the archive and set `HEPTA_E4_READER_TARGET` to its `sources/original_ddf_reader.py` before running the same test file. For either archived offline input, pass its `run` directory and `PROTOCOL.json` with the protocol's raw SHA256 to the reader, writing the readout to a new path.

These results qualify the readout consistency checks. They do not qualify model improvement, independent tasks, native owner adoption, FinalUse, settlement, or complete system costs. The active E4 run uses its previously frozen inference source and protocol; this patch changes only offline aggregation.
