# Exact 84ee format and diagnostic-pin repair

This is an unexecuted nine-path source candidate on published 84ee9c2ed0db8b20b792634d775f9b4f97a34578. Eight Rust files reproduce only the eleven hunks emitted by the actual failed Rustfmt job 131446629264. Its synthetic checkout 3fd9ee81bb321f7f7cccd89af077678dc56a5e99 has exactly the published source tree 6f1d7265ef1a58a0de1cc8da75ce142111743d85.

The remaining one-line source-QA change preserves the whole-file SHA256 check and pins the already reviewed test-only diagnostic version of neuron_cell_evaluation_host_service.rs. That service file has no formatter hunk and remains blob c1a56101fc6db3ea93155784c2776dfff3f44973. The source job actually ran 506 methods: 505 explicit OK, one failure, zero errors; native and parser stages were skipped. No prior result is transferred to this candidate.

All nine full postimages were independently fetched by immutable Git blob and matched. Every formatter edit was reversed exactly to the complete original file. No method, assertion, deadline, frame cap, caller row, or allowlist pin was removed. The runtime-accessor scan is a bounded static scan of all 61 source-closure files and the complete caller manifest, not an executed source or native gate.
