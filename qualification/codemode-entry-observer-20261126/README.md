# Observe entry before the Tokio runtime

Base: `b25482def1253d79be1529329f13c54eea2d5e94`.

The latest Intel macOS console contains 34 endpoint-startup failures across
four CodeMode host targets. Each reports a still-running child after the
unchanged ten-second wait and a nonblocking stderr read returning WouldBlock
(OS error 35). None contains an existing startup INFO event. The two passing
gRPC cases in that output do not launch the host child: one validates endpoint
credentials and one creates an in-process Unix listener. This console is not a
complete failed-attempt archive; the job reached its one-hour limit without
uploading that archive.

The first existing INFO event follows construction of the Tokio runtime and
the tracing subscriber. The new synchronous `main` makes one best-effort write
of the fixed ASCII marker `CODEX_CODE_MODE_STARTUP rust_main_entered`, then
calls the renamed private function that retains the original `tokio::main`
attribute and complete async body. A complete marker only establishes that
this Rust entry point reached that write. It does not establish runtime,
subscriber, bind, endpoint, or session readiness.

The macro remains `flavor = "current_thread"` and is called exactly once.
The lock contains `tokio-macros` 2.7.0. Its official source at the
`tokio-macros-2.7.0` tag uses the same non-test expansion for a zero-argument
function with this private name. That expansion constructs the current-thread
builder, enables the original drivers, builds it, and blocks on the original
body. The separate wrapper exposes the required observation boundary without
reimplementing that expansion. The original result, runtime configuration,
subscriber, arguments, awaits, listener setup, and endpoint output are retained.

There is one `Write::write` attempt of 42 fixed bytes including newline, with
no retry, extra flush, timer, thread, dependency, environment change, path,
argument, credential, or image output. An error or partial write is ignored.
The number of calls and bytes is bounded; synchronous stderr latency is not
separately bounded. The extra write and function boundary can alter timing.
The original test deadlines, assertions, and failure-only stderr collector are
unchanged. A missing marker remains inconclusive because writing or capture
may fail; loader/static initialization before Rust `main` is not observed.

This is a diagnostic source candidate, not a startup fix or a new passing
native test. No Rust, native process, model, or image execution qualified this
candidate. Existing natural CI must provide any later behavior evidence.

## Primary macro source

- [Tokio macros 2.7.0 entry expansion](https://github.com/tokio-rs/tokio/blob/tokio-macros-2.7.0/tokio-macros/src/entry.rs), returned Git blob `aa6523bfa18414118c5f6aaf12b3f6e9a84bc750`.
- [Tokio 1.54.1 macro documentation](https://docs.rs/tokio/1.54.1/tokio/attr.main.html) permits applying the macro to a function other than `main`.

The `tokio-1.54.1` repository tag contains a 2.7.2 macro manifest, so that
tag's entry source is not substituted for the locked 2.7.0 source above.
Official source bytes and Git framing were checked; the crate archive itself
was not downloaded or reverified by this review.
