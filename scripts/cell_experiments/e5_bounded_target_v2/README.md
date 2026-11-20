# Complete original source prefixes

Use this directory's `count_tokens.py` for current v2 readouts. Pass `--request`,
`--material-index`, `--source-prefix`, and a new `--output` directory. Supply
`--counter-result` to read an existing original counter result without loading a
tokenizer, or `--tokenizer-freeze` to run the unchanged original counter first.
The exact original material index and source-prefix bytes remain pinned.

The entry validates the original ordinal/source identities before tokenization,
keeps source refusals at their original positions, and requires complete results
for every requested record. It checks request, source, target, tokenizer, prompt,
target and original bound bindings before calculating the 1/4/16/64 prefixes.
The original counter result and request are retained separately without rewriting.
Only the new top-level `RESULT.json` provides the complete-position readout.

`run_targets.py` also requires `--prefix` and validates the complete source
partition before publishing its tokenizer request. Existing historical source
freezes and outputs remain unchanged; future execution of changed target source
requires its own source freeze covering the actual runner and new counter helper.
Static qualification retains every original gate,
64 remains false with 48 absent sources, and training admission remains false.
