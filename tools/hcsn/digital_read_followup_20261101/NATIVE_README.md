# Structured-terminal native qualification

The implementation overlays the real `NeuronRuntime` owner from
`012bcf3505cb9306d9cef094a1acc3ca34c978be`; it does not replace that owner with
a numerical mock. `native_build.py` copies the ten inherited Rust modules into
an isolated workspace, replaces `policy.rs`, and checks exact anchors when adding
the `structured_value` CLI/controller and effective-Q receipt projection.

## Recover and build the identified sources

Use a disposable checkout containing this follow-up and its pinned ancestors.
Set `REPO`, `WORK`, `RUST_BIN`, `TOOLS_BIN`, and `CARGO_CACHE` to absolute local
paths. `RUST_BIN` contains an actual Rust 1.95.0 toolchain; `TOOLS_BIN` contains
`just`; Python requires NumPy/SciPy. Choose your own Cargo cache and tool paths.
The authoritative runtime manifest is
`../digital_read_before_20261031/native/UPSTREAM_SOURCE_IDENTITY.json`: **60**
runtime files, each checked against its Git blob identity. Four unchanged gate
helpers have their identities in the inherited `build_native.py:HELPERS`.

```sh
mkdir -p "$WORK/upstream"
git -C "$REPO" archive 732e934ba496d90fbe042b8d41d479ef901643e5 codex-rs/hepta-types codex-rs/hepta-infer-core codex-rs/hepta-neuron | tar -x -C "$WORK/upstream"
git -C "$REPO" archive 012bcf3505cb9306d9cef094a1acc3ca34c978be justfile scripts/format.py scripts/run-nextest.py scripts/just-shell.py | tar -x -C "$WORK/upstream"
cd "$REPO"
python -m tools.hcsn.digital_read_followup_20261101.native_build --upstream-root "$WORK/upstream" --work-dir "$WORK/native-build" --rust-bin "$RUST_BIN" --tools-bin "$TOOLS_BIN" --cargo-home "$CARGO_CACHE" --receipt "$WORK/native_build.json"
```

Fetch the two named commits first if their objects are absent. The new candidate
uses `native/Cargo.lock`, not the unavailable dependency versions in the old lock.
The builder is offline. If the selected cache is empty, its first attempt creates
the scoped Cargo workspace before failing; populate that cache with ordinary
`CARGO_HOME="$CARGO_CACHE" PATH="$RUST_BIN:$TOOLS_BIN:$PATH" cargo fetch --locked --manifest-path "$WORK/native-build/codex-rs/Cargo.toml"`
under the same toolchain/CARGO_HOME, then repeat the build command.

Recorded build: Rust 1.95.0; real `just fmt`, `just fmt --check`, and full scoped
Cargo formatting/checking passed. The unchanged **`just test` failed** because
`cargo-nextest` was absent. The explicitly recorded fallback compiled tests with
`cargo build --tests` and directly executed all four test binaries: **178 passed,
0 failed, 1 inherited ignored**. This is not a passing nextest or whole-repo gate.

## Qualification and exact artifact bytes

Use the unpacked control-training tree containing `fit_{11,23,37,53,71}` models
and their original validation folders as `TRAIN`. No confirmation worlds are
created. All 25 heads run all five arms: old fixed/value, terminal-only, and
repaired fixed/value. The final exact-fixture package uses the original pinned
FullHX JSON, Git blob `38ad00490ee921834d05667323372da36cfc5ef4`, SHA256
`66bb4fabc2fdca0b08d7e834f6a1dfdd73aedb4cfbd1b4c594b709f742092972`.
Restore these exact bytes before replaying the unchanged verified binary:

```sh
git -C "$REPO" show 012bcf3505cb9306d9cef094a1acc3ca34c978be:tools/hcsn/round9_20261031/native/fixtures/fullhx.json > "$REPO/tools/hcsn/round9_20261031/native/fixtures/fullhx.json"
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.digital_read_followup_20261101.native_qualify --binary "$WORK/native-build/codex-rs/target/release/hepta-digital-read-before-native" --train "$TRAIN" --out "$WORK/native-replay"
```

The final run has 125 paired episodes, 390 CLI invocations, 15 refused resumes,
57 pending cold ACK recoveries, 170 actual FullHX calls, and maximum NumPy/Rust
score error `4.718447854656915e-16`. Every full run matches its acknowledged
cold resume in complete task/cell/RNG/content/ledger state and final ACK.
See `evidence/NATIVE_QUALIFICATION_EXACT_FIXTURE.json`, `native_build.json`, and build logs.
Final source digest: `7c897bdfafdf33568f41ec7a0733956cfe17af13284ef0fcf9662e5ff6122b21`.

## Replay the saved final package

```sh
tar -xzf tools/hcsn/digital_read_followup_20261101/evidence/native_qualification_final_exact_fixture.tar.gz -C "$WORK"
python - "$WORK/native-qualification-final-exact-fixture" <<'PY'
import gzip,json,pathlib,sys
rows=list(pathlib.Path(sys.argv[1]).glob('*.evidence.json.gz'))
assert len(rows)==125
for p in rows:
    r=json.loads(gzip.decompress(p.read_bytes()))
    assert r['full']['after']==r['resumed']['after']
    assert r['full']['acknowledged_sha256']==r['resumed']['acknowledged_sha256']
print('125 saved full/resumed pairs agree')
PY
```

Two earlier archives are retained as development records: the initial one used
an incomplete source-binding scheme, and the previous final package still used
a FullHX JSON with one extra trailing LF (SHA256 `491c192871abf11796bbf9d9e669eb7c98693e8ad67fdf0a82d7efda501439ee`).
After detecting that byte drift, the original fixture was restored and all 125
validation pairs were rerun with the same final binary, sources, models, and
seeds, without training or tuning. Do not attribute those earlier artifact
identities to the exact-fixture result. This
qualification retains the **frozen 17-state finite tables**: continuous renewal
is not integrated into this owner or repaired-head training. It demonstrates
validation implementation consistency and acknowledged-boundary recovery, not
task benefit, recovery from an unacknowledged effect, or production activation.
