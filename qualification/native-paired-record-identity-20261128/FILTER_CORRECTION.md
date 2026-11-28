# Pre-execution native filter correction

The earlier suggested filter `paired_record_identity` was a file name, not
the Rust module path. The original protocol and freeze input are retained.
Before any native execution, the exact eight-test selection is corrected to:

`test(paired_preparation::material_client::record_identity::tests)`

The eight functions, rejection criteria and shared native engineering budget
are unchanged. No test was silently skipped or rerun by this correction.
The first native run will use the formatted common descendant with the
Root/Agentd owner changes; native qualification remains pending here.
