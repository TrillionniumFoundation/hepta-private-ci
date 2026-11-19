# Prospective C2 source manifest strict admission (research-only HOLD_NO_GO)

On isolated desktop clone, stacked on Draft #6001 source commit
`811690416e05084c208f3f312c50d860caf867dc`.
This is a source-program admission patch, **not** a scientific experiment,
six-training completion, independent checkpoint replay, adoption or production GO.

The original C2 freeze admitted mutable JSON interpretations: missing or
wrong schema, positive `execution_authorized`, science GO, unknown source
keys, duplicate JSON keys, NaN metadata, and sources symlinked to matching
bytes. This was reproduced against actual `c2_runner.bind_program`.
That original function called `.resolve()` before the symlink check.

The patch uses exact five-field schema and eight source/config identities,
a strict no-duplicate/nonfinite JSON parse, regular source files before
path resolution, exact sibling durable publisher binding and exact SHA-256
on each input. It refuses to convert the source manifest into an execution
decision. Source-closure test fixture was updated to the exact new
manifest schema so the preexisting four tests retain their intent.

All original RED and intermediate accidental invocation/test-fixture
failures are retained as separate logs; the final combined GREEN uses
Python 3.12.3, PyTorch 2.8.0+cu128, with 24/24 tests passing.
See EVIDENCE.json for exact log SHA-256 and Git blob identities.

The actual prospective source remains incomplete (POSTERIOR-POLICY.json
absent); read-only `c2_program_freeze.py` returns exit 2 and publishes
no manifest. No original C2 job or its historical files were modified.
The original job is still finalizing/unknown, with 4/6 producer results,
two zero-byte interrupted checkpoints, no controller RESULT.json and
0/6 independently replayed trained models. Full resource costs are
unqualified. P0–P5 remain HOLD_NO_GO.
