# Anonymous weight-view transfer follow-up

Read [RESEARCH_RESULT.md](RESEARCH_RESULT.md) and [PROTOCOL.md](PROTOCOL.md).
The archived original GPT editor received only the anonymous weight packet and
semantic contract, then sealed one candidate before the host generated fresh
synthetic test inputs. All three native endpoints tie the canonical program.
This is known-mechanism representation transfer, not independent discovery.

`EVIDENCE_MANIFEST.json` pins 108 complete files and 12 chunks. Verify/extract
into a new directory with Python 3.12+:

```sh
python3 unpack_evidence.py /absolute/new/path/alias_followup
```

The archive preserves the original `neuron_experiments/` relative layout. The
original parent checkpoints, common helpers and frozen native binary are
dependencies in the initial late-information evidence archive, identified by
its SHA in the manifest. The large native binary is not duplicated here.

For replay, first unpack the initial archive into a separate new work directory,
then copy these *new, nonconflicting* follow-up files there while preserving
their relative paths. Do not replace original evidence. To execute a full new
reproduction, use a fresh work copy without the `blind_alias/results/` output
directory; the evaluator refuses to overwrite existing results. Supply the
archived editor program, candidate and seal via its required CLI options. This
reuses already known synthetic data and is a reproduction, not an additional
holdout result.

The original sealed editor is retained unchanged inside the evidence archive,
including its historical source formatting. Any later engineering adaptation
must be a separate version and cannot replace the source identified by the seal.
The separate `independent_readout_audit.json` was produced after the archive and
records a zero-forward review of the frozen result and unchanged source hashes.
