# Original cumulative-control launch failure

Run [40498180354](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40498180354)
tested source `60df5f93480e191cea88780d2ff394554182e30b`, tree
`d595f57bc57b62e850dc37930fa92c7378284c0c`. Its required outcome was **failure**.
Cold runtime installation, public material reconstruction and original-source
artifact verification passed. The first continuation's evaluation launch failed
because the isolated Python entry point could not import its sibling
`llm_runtime_parent_step` module. It did not complete the cumulative campaign.

The original 117,757,882-byte records ZIP, SHA-256
`b53e83d157c07a713fc566087b32b48fd42c0ac388628e5835071207de942b36`, is reproduced
exactly by this recipe and its pinned ci008 base. The manifest retains the
separate checkpoint archive's metadata and seven omitted `.safetensors` paths;
those checkpoint bytes were not downloaded locally and are not part of this
increment. All 11,499 retained ZIP members, including both indices, were verified.

See [the restoration procedure and limits](../INCREMENTAL_RECORDS.md).
The successful repair is retained in a separate directory. Neither run grants
product qualification or installs a child; this failed result is unchanged.
