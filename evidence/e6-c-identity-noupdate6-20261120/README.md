# E6 C signed-input repair and retained NoUpdate6 failure

The source `640bac3c258ba13534d8208a9c4a0c2977e98339` fixes the concrete C issuer mismatch exposed by NoUpdate5. Its exact source checks, required project `just fix`, blob policy and original 32 component regressions passed. The unchanged complete NoUpdate6 parent then failed with **`Invalid("Unavailable")` after C Objective construction and submission**. Complete NoUpdate, completed C, Adopt, cold D, FinalUse qualification and settlement remain unproved.

The tree is `43cec80b1143f2188838b87438138243b0c22134`; the parent is `2b8125e3f89e83aea90620c94cbc441317d4c3d0`. Only `codex-rs/hepta-agentd/src/ordinary_q24_post_a_c_inputs_tests.rs` changes between these two source commits. The exact file is 10,701 bytes, SHA-256 `3c235b172aeb2e7e656bd5e7b18087e98177538a486cc850541d0a6d18c410e8`.

## Why this repair is required

NoUpdate5's real signed request had the correct run and runtime identities, but its model tuple was the artifact bundle digest. The ordinary C fixture now retains the parsed final source configuration and signs its actual runtime and `definition.semantic_digest()`. It continues to bind `artifact_set_digest` to the separate bundle digest. This follows the already existing normal Q24 signing contract.

The original issuer/signature construction, three original input writes, product identity guard, parent body and assertions are unchanged. The change does not increase the 64-frame historical cap, 500 ms historical frame budget, request/observation timeouts, authority lifetimes or parent budget. It does not change scoring or authorize a new production owner.

## Exact validation

| Scope | Actual result | Result SHA-256 |
| --- | --- | --- |
| 47 source modules / 415 tests | Passed, no failures/errors/skips | `bb83d4b99fcf90340ce3090e5a2b8c5ee855b0410c3e27d3d6ab33a02554b06b` |
| 907 protected rows / 320 affected boundaries / original full 1,159-boundary caller CLI | Passed on the same unchanged bytes | Same source-gate result above |
| Original `just fix --locked --offline -p codex-hepta-agentd` | Exit 0; all 15,750 tracked file identities unchanged, zero untracked files | `3f6427eab65f6b567eeca6a95688cffc42099d7cc5c7041e9f03204486fdc4fa` |
| Actual source freeze and original 512,000-byte blob policy | Passed; clean exact source/tree | `526be7b28d4f5a2bff2520da86e74ea6ebd034bcad71a4486b30fd45bf36f0b1` |
| Original 11 native owner/scope cases | 11 passed | `1145f66a176965666a2cb11c145f4ca30d83f8dc2b9636577967f284b11a5256` |
| Original 16 retirement/drain/recovery cases | 16 passed | `26cff4b62a3b7acfbb3ecc2c9c0d7c92e22ccd3d8d3b76530aec37316f09d311` |
| Original two plus three real delivery cases | 5 passed | `0005bd3a3aa0bdcf69b344b231b4d530a8bda9881ba21a45dc93fb7789b1e2d0` |
| Original complete NoUpdate6 parent | Failed; original source/compiler/binary identities and mount cleanup remained valid | `23a53e8ea3c06b3ee6944751e97552e1bb49ad7350fbce8ca053dd54944fd0a8` |

The project fix used the repository's actual recipe, `cargo clippy --fix --tests --allow-dirty`, with the original locked offline environment and two build jobs. Its existing warnings are retained in full. This result is not a separate `-D warnings` qualification. Compile-only listing is recorded separately and contributes zero native cases. The exact native case names and complete JUnit outputs are retained; case counts are not substituted for their identities.

## What the failed parent actually reached

The parent started at `2026-11-20T08:04:32.830913Z`. The original dedicated UID, protected binds, helper, product and test executable preparation checks passed. Historical requests 1 through 55 were observed; the 64-frame limit was not reached.

The former C signature/definition rejection was crossed. The ordinary control server received C's `objective_start`; Objective construction returned after 837 microseconds and submission began after 1,042 microseconds. The historical continuation then reported `Invalid("Unavailable")`, followed by the original delivery's `CommitUncertain` and fenced joined result. The control handler returned at about 2,009,256 microseconds and its reply write failed. These ordered observations are retained; the precise source of `Unavailable` is still under investigation.

Physical originals show C's source journal at 6,456 bytes with a 672-byte witness, and C's Cell journal at 654 bytes with a 224-byte witness. C's generation journal remains a 40-byte header with a 112-byte witness. The source contains request/input records for `ordinary-original-c`. These facts demonstrate additional actual work after NoUpdate5; they do not establish C completion or a final accepted learning result.

The old NoUpdate5 evidence remains separately preserved in `../e6-read65-noupdate5-20261120/`. Neither its failure nor this one was overwritten. The static whole-path estimate of 63 frames remains a calculation, not an observed complete result. Direct fault injection into the actual Root client's post-read remains untested; the delivery witness-capacity recovery control is a different test.

## Evidence custody and reproduction

`MANIFEST.json` binds 229 exact originals totaling 67,362,373 uncompressed bytes. The archive is 1,025,424 bytes, SHA-256 `883a9b3af8c599c143a3c575b71863d295f324cd5f608c2ba58ff2d2f4b77200`, split into three parts no larger than 480,000 bytes. `python3 reassemble.py` verifies every part, the whole archive, membership and all original member identities without executing or extracting its contents. All 229 originals were independently checked after download.

The physical inventory covers 785 files. The archive copies 52 explicitly selected non-key physical files, including the actual C journals/witnesses and child logs. Key bodies, unknown authority bodies, potential key-bearing business-image bodies and the original immutable executable remain on the host. Their metadata and the explicit exclusions are retained. No file was changed in place to manufacture a completed state.

## Actual cost scope

The source gate took 645.156 seconds, the project-fix command 268.465 seconds, and the exact freeze 1.544 seconds. The original 11, retirement 16 and delivery five commands took 94.408, 10.989 and 0.716 seconds; the first interval includes actual recompilation. Parent preparation includes 32.966 seconds for helpers, 5.424 seconds for products and 1.266 seconds for library listing. The parent command took 75.947 seconds; its complete owner took 127.650 seconds; the enclosing component-plus-parent pipeline took 237.429 seconds.

These windows overlap and cannot be added as independent costs. Previous cache acquisition, failed source/compile attempts and previous native parents remain linked. Small status/result reads occurred during the parent; no zero-system-activity claim is made. Whole-system energy, network bytes, storage byte-seconds and provider charges were not measured. No training gain or economic proof-of-useful-work claim follows from this engineering validation.
