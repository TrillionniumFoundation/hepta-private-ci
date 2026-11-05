# Python runtime contract v2

The ordinary CPU loader requires an independently supplied byte contract for its
Python environment before it starts a model process. Package-reported versions
are supplementary observations; the contract binds actual interpreter and
installed file bytes.

## Required configuration and wire versions

`hepta-smollm-cognitive-host-v2` requires `worker.runtime_snapshot`, a protected
`{path, sha256}` pin of at most 16 MiB. There is no default environment and no
capture-at-load fallback. The declared snapshot uses the existing
`hepta-controlled-cold-runtime-snapshot-v2` format produced by
`scripts/hepta_smollm_runtime_snapshot.py`. Its original recorder requires the
complete locked CPython 3.12 CPU runtime, wheel installation report and import
probe. Creating an arbitrary JSON object with that schema string does not
qualify a model or its environment.

The ordinary CLI accepts `owner-v2`; old `owner-v1` is unsupported. The unchanged
Cell-v2 envelope embeds the new self-versioned owner object. The native control
inputs are `hepta-smollm-neural-native-check-v2` and
`hepta-smollm-controlled-cell-native-check-v2`, with an explicit snapshot path
and SHA-256. Old native v1 inputs are rejected.

Worker plans, Ready records, replies and stop frames use
`hepta-smollm-neural-read-worker-v2`. Inference requests retain
`hepta-smollm-inference-input-v1`, and the model's single-token action semantics
remain `hepta-smollm-single-token-action-score-v1`. The execution digest starts
with `hepta-smollm-runtime-bound-execution-v2` and binds the snapshot's exact
SHA-256 alongside the complete project sources, material pins and actions.
Previously signed execution digests cannot silently acquire the new contract.

## Admission before Python startup

The Rust host verifies the configured interpreter's canonical identity and
actual bytes. It verifies every declared snapshot file, reconstructs the exact
managed inventory under the private venv and stdlib roots, and refuses missing,
extra or changed files. Files and traversal have explicit count/size bounds.
The existing startup execution object supplies every cancellation and deadline
check; the new work does not grant another startup window.

This profile supports an unpacked stdlib. It refuses startup ZIP files, changed
bootstrap stdlib aliases, and adjacent `._pth` search configuration at the real
interpreter, configured launch path or declared shared-libpython directories.
These paths matter before the worker can verify itself. `LD_*` and
`GLIBC_TUNABLES` overrides are rejected before the process is spawned.

The ordinary host's existing 120-second startup deadline and the transport
owner's existing 35-second transfer deadline keep their separate original
owners and limits. Hashing costs consume the actual startup allowance. This
change has not established that a complete model runtime can pass within that
allowance; an over-budget environment must fail honestly.

## Guarded imports and Ready

Both the supervisor and its worker enter with `-I -S -B` and an explicit unused
bytecode prefix. The helper restores only the declared stdlib, lib-dynload,
private site-packages and project source roots. Site customization and `.pth`
execution are not part of this path.

The helper and Python modules are compiled from the same bytes whose hashes
were checked. Ambient `.pyc` files cannot substitute for those source bytes.
An undeclared module is rejected before its source loader executes it. The
finder preserves the standard distribution metadata discovery interface, which
real dependency version checks need. Native extension files are checked before
loading, and loaded module paths and executable mappings are checked against
the declared runtime/project closure before Ready.

The project source closure has thirteen mandatory members: `contract_wire.py`,
`llm_adapter_contract.py`, `llm_base_material.py`, `llm_inherited_runtime.py`,
`llm_neural_read_worker.py`, `llm_parent_material.py`,
`llm_python_runtime_contract.py`, `llm_runtime_pilot.py`, and the existing
`devnet-v1`, `ledger-v1`, `model-family-v1`, `work-profile-v1` and
`model-family-smollm2-135m-v1` configuration files. Each concrete absolute path
is independently pinned. The new execution-source profile preserves all prior
V10 source paths and adds the complete runtime admission closure.

## Evidence boundaries

This is static drift refusal with guarded Python source execution. Filesystem
namespaces and native libraries are not held immutable across all check/use
boundaries. The trusted host, kernel, system loader configuration and hostile
concurrent namespace replacement remain outside a hermetic claim. Cooperative
deadline checks cannot interrupt a filesystem operation blocked inside the OS.
Direct research Python entry points do not acquire the Rust host's pre-spawn
bootstrap guarantee.

The legacy study forward remains worker-v1 and explicitly refuses the new V11
runtime source profile. Public-initial's actual helper graph uses the original
runtime pilot child and does not call that legacy forward. Historical source
tuples and evidence remain unchanged; they are not evidence for the new host.

File/process unit controls and transport/exec-contract probes are not a real
Torch/model Ready, installed artifact, device/VRAM owner or ordinary multi-Cell
qualification. Native Rust execution results must be reported from the actual
supported host toolchain, independently of formatting. During implementation,
`just fmt` used installed Rust 1.95.0; the host build/test toolchain is 1.96.0.
