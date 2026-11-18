# Preserved first extended E4 attempt

This is the actual failed execution of protocol `951c24b55bf1afcc9e4e6dc57aaf746bf52f7c4836da0d57c3f9acd386612b8e`, following the E2 owner's verified release. It is not a completed Circuit study or evidence of an independent task/source gain.

The real child process exited 1 during shared-pool initialization. The unchanged `TRAINING.parameter_after` tensor hash gate rejected the active adapter. The traceback does not label the adapter; it must not be described as proof that the first adapter failed. No pool snapshot, graph result, generation receipt, or search result was produced. The strict gate and all original files remain unchanged; a corrected loader requires a new source/protocol freeze and a new output directory.

## Original evidence

- `e4-originals.tar.gz`: 691,623 bytes, SHA256 `86268f5af2e7855bd5d864cf236d46f47e893f34106be39097d6318049b8a27f`.
- The archive contains 240 members / 216 regular files: the frozen protocol and executed source, original B source/closure and comparison, engineering gate, Run02 inputs and model manifests/training receipts, owner argv/wait/stdout/stderr, and the failure receipt. It contains no model weights.
- The archive was fetched in version-bound chunks, every chunk was SHA256 checked, and the complete local file matched the original archive SHA256 before publication.
- `run_extended_circuit_once.py` is the exact executed launcher, SHA256 `b584f456fc83b06f655efc732e34172659ae3470f5a50df2ca558da155d40d05`; it was formatted with unchanged Python AST before execution.
- `FAILED_RUN_READOUT.json` is the unmodified output of the standalone reader from #6674, SHA256 `b19a126df3ff990c39851cbe182a1eb6f044552dc72a0de39896971ae2d6bd6b`.
- `OWNER_RESULT.json` is the original archive/owner receipt, SHA256 `eda5aa09623391d18426e0671c19ae2a69a46673b3b6efe07bb747fe5f4b8a25`.

## Cost and interpretation

The actual owner wait covered **110.117431087 seconds**; the child scope after admission covered **50.508930403 seconds**. These are nested scopes and must not be added. Initialization consumed time even though no model generation completed. Complete model/token totals remain unknown in the failed reader, while completed-graph lower bounds are zero. Energy, monetary cost, GPU active time, and full-system cost are unknown.

The 162 graph / 306 call figures in the protocol are planned counts, not executed results. The same retained Run02 adapters and old A/B tasks were selected; the independent sample increment is zero. This failed attempt remains part of the cost history of any subsequent corrected candidate.

To inspect the raw evidence, verify the archive SHA256 and extract into an empty directory. The reader in #6674 can be run against the extracted output and protocol; it rebinds original absolute artifact paths for offline inspection and should retain `INCOMPLETE`.
