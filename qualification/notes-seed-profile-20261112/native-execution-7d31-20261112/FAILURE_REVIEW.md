# Exact 7d31 ordinary validation: original pre-build failure

Original durable job: `1a1cf8ed400-2564-1a56`, stable key `neuro4-act6243-native-7d31-862531d-v1`. Preserve this invocation and its output directory; do not relaunch the same request.

The actual driver TERMINAL is **FAILED** at **v8-prepare** (exit 1, 2.617141261929646 seconds). Its original source clone, exact fetch and detached checkout each exited 0. The driver checked all 13,722 tracked inputs against the Git blobs and reports equal before/after inventories for exact commit `7d31bf9677748330ae17efe964de48d98ba5e542` / tree `cedbad6b47e4ff8db4f87efc9169a4b5c13412be`. The large source inventory files remain on the host; this evidence bundle includes the driver's actual terminal claim and reviewed-input/lock records, not a reconstructed full inventory.

The complete 3,755-byte V8 log has SHA256 `a439c725dbb8137badcc0ec23c79c1d1b0d782f0fe5bbfb4c0a3f3242853fabd`. It records `http.client.RemoteDisconnected: Remote end closed connection without response` in the unchanged `codex_package/v8.py::download_file` while fetching the official release checksum. It did not reach artifact checksum comparison, original caller proof, native binary compilation, Rust tests or formatting. Missing later result files do not constitute passing or failing Rust tests.

Cargo.lock binds V8 150.4.0. The requested manifest is:
`https://github.com/openai/codex/releases/download/rusty-v8-v150.4.0/rusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.sha256`.
The original resolver always downloads this manifest, then uses its complete two-artifact checksums to validate any existing cache. It must not be replaced by an unchecked archive or an environment override that skips these checks.

The actual initial resource record has uid/euid 1000, MemAvailable 113011544064 bytes, free disk 378434854912 bytes, and load average [1.0, 0.85302734375, 0.60888671875]. The four predeclared just/nextest/protoc/DotSlash binary hashes match. Rust/cargo/rustfmt/rustup versions and observed binary hashes are preserved separately; their request pins were null, so these are observed values rather than independent expected-hash provenance.

Readback records preserve the original complete UTF-8 file strings, versions, sizes and individual SHA256 values. They are independent file snapshots, not an atomic multi-file snapshot. REQUEST_PLAN.json retains the exact pre-admission proposal status label as immutable input; execution state comes from the separate actual TERMINAL.

No Root or owner authority is established. `owner_decision=null`; scientific qualification remains HOLD. No new B/C scientific actors were requested in this job. The next validation, if the external connection problem is resolved, needs its own identity and output directory and must pass the unchanged original gates.
