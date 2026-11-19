# Original frontier 480e8353: review and qualification state

## Scope and decision

Original source: `480e83532df57ec691ce70ff7ecb572717887a7e` (`fix/ndu-v4-fractional-outcome-mass-20261024`). Its original parent is `71731cecd209580358d847955a6e16751fe1323a`; its tree is `e6ac5eeb2e9d51a24a3d46cdf2ed286c7f05fbe1`. The unique common base with frozen integration `094132189b7f94b941ac61cb3c812cb9a51cdc2b` is `f8c9419df6ddeb36ff8b522a50219981fb8d9345`.

At that frozen integration, this whole source frontier covers 17 pending ordinary branch names and changes 132 paths: 131 additions and one divergent existing file, `codex-rs/hepta-ndu/src/lib.rs`. All 131 unique incoming blobs were recovered and independently verified by original Git blob SHA-1, byte length, and SHA-256. Their combined uncompressed size is 3,532,328 bytes. No original source, tests, historical failure, or scientific claim boundary is dropped.

**Status: this whole original frontier has passed source review, 147 original Python tests, all six original Rust tests, actual binary parity, canonical Bazel lock checking, actual Bazel target discovery, and the required final scoped fix/format sequence.** The unpublished final source commit is 74b4d37db870120b3795d849734d9b4e811d46e4, tree c9dd5dcf42c96f34fa8846690a562a4b3aad41e9, with exact ordered parents 2df7993caa719c46d316f320e90b16d96b8ff2d7 and the original 480e source. All 132 affected base postimages were unchanged between 094 and 2df799. Publication and reconciliation remain owned by the parent integration task; this receipt does not claim that main has advanced or any branch has been retired.

The latest protection proof excludes all 498 protected historical pins from the original source's 33,890-commit ancestry and preserves all 478 live protected HIA names. The added HIA tip `6dbde7c5df25cf7ff3964ce5bada5933ec346ba1` and its original parent are included in that check. No protected ref has been modified.

## Rust behavior and preservation

The incoming Rust feature is a finite local feedback-generation session owner with a bounded stdin/stdout protocol and a small executable. It has no production dispatch or operating-system authority. Caller-provided digests bind the session's declared input and outputs; the implementation does not treat them as proof of caller identity or kernel execution.

The configuration requires nonzero session, cost, and initial-latent identifiers; an initial budget large enough to emit; at most 64 refinements; and a portfolio identifier bounded by `u16`. A snapshot contains session, version, refinement depth, portfolio, and latent digest. The remaining budget is private session state; the owner validates its phase and the snapshot version before spending it. Action admission rejects nonfinite values, duplicate actions, missing emission, inconsistent fixed costs, and stale snapshots before mutating state.

An accepted action charges its fixed cost before advancing to the matching acknowledgement phase. Refinement additionally requires both available depth and a checked sum of refinement plus reserved emission cost. The owner chooses refinement only when its value exceeds emission by the original `1e-12` threshold, preserving deterministic emission on a tie regardless of action-table order. Acknowledgements must match the exact session/version/depth/portfolio and nonzero expected digests. Emission seals the session after four nonzero output digests; subsequent actions fail.

The TSV transport bounds each input line at 4,096 bytes, reads at most 4,097 bytes to detect excess, and fails oversized or unfinished sessions. It has no network operations or arbitrary command execution. The original binary only connects this owner to buffered stdin/stdout. Current `Digest32::is_zero(self)` is compatible with the incoming implementation.

The original `lib.rs` delta contains precisely two private module declarations and nine explicit public exports. The genuine normal merge added those declarations/exports to the complete current library. The current 335-line library, its `forbid(unsafe_code)` directive, and every existing export/guard remain as an exact line subsequence. The four new Rust files preserve the incoming blobs exactly:

| Path under `codex-rs/hepta-ndu/` | Git blob | SHA-256 |
|---|---|---|
| `src/bin/ndu-feedback-generation.rs` | `e1999faac139dee3d3ca8a44a218250fe7a767e9` | `206117e7ab1f6c721aae9d14950f0036d6ca3e30e86844bd5b5feb430a3df1e1` |
| `src/feedback_generation.rs` | `bcd8beeacbada65810c9d2addbf37dcac64e1449` | `520f53dcbf8abf015602f0eaeb2835b5a300787b815716e33ba340e8c4fa5e47` |
| `src/feedback_generation_protocol.rs` | `1be2be0b3df960012025d8f7871afa2631d977c9` | `40ef09bcc845c94b5be0112d8af0fbdbf1049aa7392603c9cc6c521f94b025b0` |
| `src/feedback_generation_tests.rs` | `6a6d653afb660d48dd4e89dee78c326c66486bdf` | `3ae374998d29f2ec876b1506ea764f5a66f28eaccfdeb656cce62bc75938f376` |

An independent reviewer verified the five original Rust blobs, the integer/phase and protocol boundaries, compatibility with the current digest API, and pinned Rust 1.96 rustfmt output. All five original files are already in the pinned formatter's canonical form. That static review does not replace final combined-source compilation/tests. Its report is `ci-audit/480e-rust-review-notes.json` in the parent task, SHA-256 `c2aae7be48de68c92d598240c0953b67b292af0694786450cd1177216e37f254`.

No dependency changes were introduced. An explicit Cargo binary declaration names the exact existing automatic target and path so the new target is represented in a manifest watched by rules_rs. Actual Bazel query resolved //codex-rs/hepta-ndu:ndu-feedback-generation, and the canonical lock check passed. Cargo.lock and MODULE.bazel.lock remain byte-identical to the base; no lock update was needed.

## Python and research payload

The 127 non-Rust paths comprise 66 Python sources, 37 JSON records, 12 Markdown documents, four workflow YAML files, three shell launchers, two PNGs, two SVGs, and one text file. `python-source-index.json` records imports and the 147 original test functions. The active experiment is a finite, synthetic, closed-world research program. Existing blocker ledgers, failed primary-effect gates, and restrictions on extrapolation remain original bytes.

The v1/v2 code separates model outputs from externally supplied truth used only by offline scoring. It preserves matched work accounting, fixed model parents, immutable stream state, emission sealing, reserve/cost constraints, independent exhaustive-policy comparisons, and finite-difference gradient checks. The v3 code adds observed latent feedback, exact finite stopping-tree/nature enumeration, independent public/witness information, and a persistent native bridge. The witness is paid and nonrepeatable in the synthetic protocol; a known simulated witness probability is not represented as an empirical reliability estimate.

The v4 modules are standard-library finite portfolio, information-acquisition, joint-evidence-generation, and counterfactual-audit implementations. The original tests cover exact rational probability support and path mass, causal public-state replay, reserve/activation budgets, fresh-root custody, immutable admission, extreme and near-neutral risk, complete policy replay, and negative numerical inputs. Assertions were neither removed nor altered.

The original persistent-process parity program, `v3/native_parity.py`, is standard-library only. It runs 256 randomized finite sessions plus a `u64` cost-overflow case, reverses action-table order, checks nonfinite/duplicate/missing-emission/cost/phase/snapshot/session/output-digest rejections, and compares every real binary response to independently generated expectations. Its receipt binds the actual Rust sources, Cargo files, BUILD file, script, and executable digest. It was executed unchanged against the real newly compiled merged-source binary: 5,400 requests, 256 random sessions plus one overflow session, and zero mismatches.

The Python bridge invokes one explicitly selected local binary with argument-vector `Popen`, without a shell. It is an experimental trusted-child pipe interface. Its synchronous exchange lacks a per-message timeout; it is not being promoted to an authenticated production service boundary.

### Optional natural-media scripts

These files are explicit research CLIs and are not run by the unit qualification. They require caller-supplied private output/asset directories and write separate receipts.

- `natural_io/ingest.py` downloads the fixed licensed public fixture, caps the download at 20 MiB, verifies its pinned length/SHA-1 before decoding, invokes ffmpeg/ffprobe with argument vectors and timeouts, validates finite tensor shapes/content, and retains attribution. The fixture is one recording with derived frame/audio/video and a human description; it does not claim four independent capture modalities or quality validation.
- `codec_smoke.py` verifies exact upstream source and weight sizes/SHA-256 before importing the pinned codec source or loading tensor-only weights. It validates actual input artifacts, finite values and shapes, freezes parameters, records executed convolution work and exclusions, and prevents overwriting an existing output directory or evidence receipt.
- `text_model_smoke.py` pins model revision, each metadata Git blob, and the safetensors weight SHA-256/length. It caps downloads at the pinned lengths, loads local files with `trust_remote_code=False`, bounds caption tokens and generated tokens, and records interface-only scope. No foundation-model or NDU benefit claim is asserted.
- The active `audio_codec_smoke.py` validates its pinned CPU runtime, installed archive/source/weights/license, fixed input, checkpoint metadata schema, and CPU tensor state. It calls `torch.load(..., weights_only=True)` and strict tensor loading with no unsafe fallback. It records the fixed right padding/crop and actual reconstruction checks.
- Historical `audio-codec-001-source.py` and `002-source.py` preserve their original upstream `DAC.load` call and the original failed/earlier attempts. They are archived evidence, not the active loader and not unit-discovered code. The active implementation is byte-identical to archived attempt 003. Preserving these originals does not endorse running the earlier loader.

All seven natural-media receipt-to-script SHA-256 bindings checked in `historical-source-bindings.json` match their retained original source. No external weights, media, or historical output archive was downloaded or re-executed by this consolidation review. Local file paths recorded in the historical evidence remain historical; they are not being asserted as current accessible artifacts.

### Historical outcomes and figures

Both original PNGs were decoded, verified, and visually inspected. They are research plots with explicit scope limitations. The amended v1.1 plot preserves the primary-effect failure, an interval crossing zero, and the statement that observed nondominance is descriptive. The corresponding SVGs contain internal SVG references and verified embedded PNG data; neither contains script, foreignObject, event handlers, or external resource references.

The v1 summary pins three older source versions (`control.py`, `protocol.json`, `run_experiment.py`) different from the incoming latest versions. Its historical source hashes are retained and this drift is explicitly recorded. The amended v1.1 summary's nine listed sources all match the incoming original files. Old Rust parity receipts also bind their historical pre-final-format files and lock; they are evidence of that run and are not reused as current source qualification.

Two exact original PNGs exceed the existing 512,000-byte repository budget. Preserve their exact original bytes using the existing content-pinned allowlist format, with both entries included in the reviewed merge:

| Original path | Bytes | SHA-256 |
|---|---:|---|
| `experiments/multimodal_output_portfolio/evidence/local_preflight_v1.png` | 692,744 | `a96422565784a401bc415cd19fad4c23838ffa96f6837e0df407bc58d43aad53` |
| `experiments/multimodal_output_portfolio/evidence/local_preflight_v1_1.png` | 701,542 | `c5308e3adc06f88fac84e9c5d9a935649a832449b3089ba953aab27a5ae20259` |

No other incoming original exceeds the default limit. Resizing, re-encoding, or a directory-wide exception would lose exact historical custody and is not proposed.

## Workflow and launcher review

All four workflows use full 40-hex action revisions, `contents: read`, and checkout credentials disabled. The dedicated old experiment workflows only respond to their literal research branches and original request paths. The hosted recovery workflow pins the old source and records the recovery separately. No new secret or permission write capability is introduced.

The v4 shadow workflow is a pull-request/workflow-dispatch standard-library test job for this experiment subtree. It checks out the literal event head and verifies the commit. It uses `pull_request`, not `pull_request_target`, and does not download models or run training. Its older, still fully pinned checkout revision is preserved; no repository instruction was found that permits silently substituting an action's code while claiming original-byte custody.

The three shell launchers pass `bash -n`. Their runtime/source/request checks remain exact, require isolated outputs and their declared execution tier, and retain failure logs/pipeline exit codes. They install pinned CPU packages only when explicitly invoked. No workflow was dispatched and no launcher was executed by this review.

## Executed checks

| Check | Exact scope | Outcome |
|---|---|---|
| Source custody | 131 unique blobs / 132 original paths | Original Git SHA-1, size, SHA-256 all match |
| HIA exclusion | 478 live protected names / 498 pins | Zero source-ancestry overlap |
| Codespell 2.4.1 | All 132 originals, existing repository ignore list | Exit 0, no output |
| Static payload parsing | 66 Python compiles, 37 strict JSON, 3 shell scripts, 4 YAML/action pin lists, 2 PNG, 2 SVG | All pass |
| v1 original tests | 16 tests, Python 3.12.3 / NumPy 1.26.4 / Torch 2.5.1+cpu | 16 pass, zero skips |
| v2 original tests | 7 tests, same pinned CPU runtime | 7 pass, zero skips |
| v3 original tests | 33 tests, same pinned CPU runtime | 33 pass, zero skips |
| v4 original tests | 91 standard-library tests, Python 3.12.14 | 91 pass, zero skips |
| Native test source stability | All 66 incoming Python sources | SHA-256 unchanged before/after |
| Original Rust formatting | Five originals, pinned Rust 1.96 rustfmt | All byte-identical formatter outputs |
| Combined Rust compilation/tests | True merge of 2df799 and original source, Rust 1.96, just test --locked | Six original tests pass across seven compiled binaries; 318 unrelated tests filtered |
| Actual native protocol parity | Original script, real compiled binary, bound source and executable hashes | 5,400 requests, zero mismatches |
| Bazel metadata and target | Canonical just bazel-lock-check and actual query --lockfile_mode=error | Both exit 0; both lockfiles unchanged |
| Final scoped fix/fmt | Required commands after tests | Both exit 0; five reviewed last-use clone removals in old tests, no formatter change |
| Final source identity | Native detached HEAD/tree and 2,456 exact materialized files | Clean and exact final source commit; original incoming assertions unchanged |

The three Torch groups took 6.2007 seconds total in an isolated CPU environment. The v4 unittest run took 11.811 seconds (12.1888 seconds whole subprocess). Source-changing formal experiment runs, heldout evaluation, model downloads, and GPU work were not part of this qualification.

The actual sequence followed root AGENTS: just test --locked -p codex-hepta-ndu feedback_generation, production binary build, the unmodified native_parity.py, canonical Bazel lock check and target query, scoped just fix -p codex-hepta-ndu, and final just fmt --base 2df799. No tests were rerun after final fix/fmt. Clippy removed five redundant last-use clones in two existing test files; full contexts, owned-field type chains, exact postimages, and preservation of every assertion are recorded in the two final-clippy review files. The six incoming test functions and all current library exports remain exact. Root owns current-head reconciliation and remote publication.

## Evidence index

- source-equivalence.json records every original incoming postimage and the four intentional additional paths.
- all-original-source-manifest.json, frontier.json, and lib-original.diff retain source and merge provenance.
- protection-and-coverage.json records the complete frozen ordinary/protected graph proof and all 17 newly covered ordinary names.
- python-source-index.json, nonrust-static-validation.json, and historical-source-bindings.json contain the complete payload review.
- v1-v3-original-tests.json, v4-original-tests.json, and their stderr files record all 147 original Python tests.
- native-rust-qualification.json and original-rust-tests.stderr record the six original Rust tests and actual binary execution.
- native-parity.json and its exact gzip transcript contain all 5,400 protocol exchanges.
- native-bazel-qualification.json, query output, and lock-check logs record actual target discovery and unchanged canonical locks.
- final-fix-format.json, its exact diff, and the two final-clippy review files retain the mechanical changes and independent reasoning.
- native-final-source-binding.json and native-final-source-manifest.json.gz bind the final native worktree to its exact Git tree.
- artifact-integrity.json gives published hashes, original stream hashes, and any path redaction transform.

The first native strict import lacked 97 original historical root trees; their exact original type/OID/SHA-256 bytes were imported into the private verification store and the strict import passed. A narrow initial Bazel checkout lacked rbe.bzl; 12 exact Bazel source files from the same Git tree were added before the successful canonical check. These were transport/materialization failures, not waived tests or lock rewrites. Full private operation logs and receipts were retained. No broad historical blob hydration, remote ref write, model download, or GPU allocation was performed for this Rust qualification.
