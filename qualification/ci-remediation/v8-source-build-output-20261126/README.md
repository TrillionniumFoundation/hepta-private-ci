# Observe the existing Windows V8 source build

This candidate adds only Cargo's `-vv` flag to the existing Windows upstream
source-build command. It does not resolve a demonstrated performance defect or
qualify either Windows build. No new build or CI retry was run for this change.

## Original observations

In run `45616349201`, source jobs `139233236667` (x86_64 MSVC) and
`139233236672` (ARM64 MSVC) completed with `cancelled` conclusions after about
30 minutes. Both stopped in `Build upstream rusty_v8 sandbox release pair`;
staging, smoke-linking, and upload steps were skipped. The workflow's original
job deadline is 30 minutes.

| Original log | Bytes | SHA-256 |
| --- | ---: | --- |
| `139233236667` | 157,202 | `7111839cb26560368bf528c83e77425877d90d950f2365d821728b4f4fb47399` |
| `139233236672` | 157,016 | `8355c4907fec315fb96955eca4d8333cfb52fe1c47a3525591d556555ee62190` |

Both source caches missed. The x86_64 cleanup log names two surviving
`clang-cl` processes, proving that native compilation had been reached. It does
not identify what dominated the elapsed time. ARM64's cleanup does not provide
the same positive evidence; absence of a compiler name is not proof that
native compilation never ran. Normal output does not separate download,
configuration, or individual native-build work during the long quiet interval.

Both jobs checked out merge `4eebcef0c284da9a1964d6c01c15c0f219f7aff9`, whose
complete tree equals source `4be2e45d4c90fe539abf61814fa9b362d8922881`:
`28a74dbbf9b668c4691a93c8fd15c5ae2b4c92e9`. The pinned upstream is rusty_v8
150.4.0, commit `5c15a6995c9bb4bacd3e341b59fff32c909c80bf`. Its `build.rs`
SHA-256 is `cd979d31a70f3d5a2d240019a52de2412a803690f8d3b441bf8254c548588c31`.
The configured target/release/gn_out cache matches that source's output layout;
this investigation has not demonstrated a cache-path or dependency-layout bug.

## Why this flag

The [Cargo build-script documentation](https://doc.rust-lang.org/cargo/reference/build-scripts.html#outputs-of-the-build-script)
states that normal builds hide build-script output and that `-vv` displays it
when the script actually runs. The added output is intended to identify the
stage reached by the next normal source build. A cache hit that avoids running
the build script naturally will not produce a new script trace.

The candidate preserves the pinned Cargo toolchain, upstream source, targets,
release profile, sandbox feature, locked dependencies, cache paths and keys,
runner matrix, timeout, failure propagation, and downstream smoke-link gates.
It adds no dispatch, retry, runner replacement, permission, or artifact bypass.
YAML structure outside the one command string is unchanged. `actionlint`
1.7.12 and `git diff --check` pass; native qualification remains pending.
