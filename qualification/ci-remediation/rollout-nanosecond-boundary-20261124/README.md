# Rollout anchor nanosecond conversion

The Windows native consumer job for source
`676d59ef602e59790a58614541bfb92325bdc71f` stopped at
`rollout/src/list.rs:335`: `Anchor.ts` had become `codex_utils_time::Timestamp`,
but its consumer still called the old `timestamp_nanos_opt` method.
[Observed job 138566329525](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45428321717/job/138566329525)
reported E0599 for both the directory/schema and prompt-consumer builds.

The fix uses the existing signed duration from the Unix epoch and retains the
checked i64 nanosecond conversion. This preserves the previous narrow integer
range and epoch fallback, negative fractions, represented-leap normalization,
and the unchanged thread ID. It adds no new time API or production dependency.

## Executed qualification

`prepare_oracle.py` extracts the actual conversion implementation verbatim and
compiles the actual time utility source in a small, independent Cargo graph.
Only the unrelated thread ID is replaced with an opaque copyable fixture value.
It compares the result against the exact previously active Chrono 0.4.43 code.
Chrono is an oracle dependency only; neither production dependency lock changes.
`oracle.Cargo.lock` retains the complete graph used by the executed qualification.

- 1,010 valid instants, each with two ID alternatives: 2,020 matching results.
- 197 out-of-range values exercise the original epoch fallback.
- 20 represented leap seconds and 68 identically rejected component pairs.
- Both i64 nanosecond limits, their adjacent values, negative fractions, broad
  calendar limits, and 512 deterministic samples are included.
- Ten actual time utility tests and the differential oracle: **11 passed**.
- Isolated `just clippy -- -D warnings`: **passed** on Rust 1.96.0.
- Repository `just fmt` and `git diff --check`: **passed**.

The repository also adds a complete Cursor JSON regression with 12 date inputs
and both ID alternatives. The full rollout/native consumer build and that full
consumer regression were **not** executed locally; they remain normal CI gates.
The isolated oracle is not a replacement for those gates.

An initial attempt supplied the entire workspace nextest configuration to the
isolated graph. Nextest rejected overrides naming absent packages before running
tests (exit 96). The generated standalone configuration preserves the workspace
default timeout/retry policy without naming unrelated packages. The production
nextest configuration and all production test requirements remain unchanged.

## Reproduce

From the repository root with Rust 1.96.0, `just`, and `cargo-nextest` available:

```sh
TASK_NANOS_ORACLE=/tmp/rollout-nanosecond-oracle
python qualification/ci-remediation/rollout-nanosecond-boundary-20261124/prepare_oracle.py --output "$TASK_NANOS_ORACLE"
just test --manifest-path "$TASK_NANOS_ORACLE/Cargo.toml" --config-file "$TASK_NANOS_ORACLE/nextest.toml" --locked --success-output immediate
just clippy --manifest-path "$TASK_NANOS_ORACLE/Cargo.toml" --locked -- -D warnings
```

The source-binding receipt records hashes of the actual conversion and its
containing file. `result.json` records this run's checks and scope. A targeted
first-party scan found no other confirmed unsupported `Timestamp` calls among
the old epoch, calendar, timezone, duration, and formatting APIs. Same-named
methods on `Cursor`, `RolloutFileName`, integers, V8, and `time::Date` are retained.
That source scan is not a substitute for compiling every consumer.
