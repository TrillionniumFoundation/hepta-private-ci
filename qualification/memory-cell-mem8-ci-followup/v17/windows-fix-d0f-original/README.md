# Original Windows sandbox scoped lint: dirty-source rejection

This is the complete retained evidence of the one admitted run **43062162500**, job **130667533098**, attempt **1**. The original job failed. Its failure is not rewritten as a pass.

The harness was `23d9f41532e5e6310ca791a5b849ab1cff7466eb`, tree `4bddc28958d0bde7d2735d0a626c2052d33ccb24`. The separately checked source was `d0f6507e08f7f5c5855f5164d07c049a34d1a6d9`, tree `658fa040046285116b1fd81b94ff8c96444072ad`.

| Original phase | Actual outcome | Retained limit |
| --- | --- | --- |
| Build the two sandbox helper binaries | Exit 0; 877.422 seconds; clean before/after | Actual compiler-artifact identities and driver-observed executable/sibling byte hashes are retained. The PE binaries themselves are not archived here. |
| `just fix --locked -p codex-windows-sandbox` | Exit 0; 545.797 seconds; one source rewrite | The command finished, but the source-integrity gate rejected the dirty tree. |
| Collection | `partial_or_failed` | All 153 original ZIP members are retained, including 152 manifest entries, both raw command logs and all recorded snapshots. |

The only changed file was `codex-rs/windows-sandbox-rs/src/setup_process.rs`. Clippy replaced `.map_or(std::ptr::null(), |path| path.as_ptr())` with `.map_or(std::ptr::null(), std::vec::Vec::as_ptr)`. The buffer remains the same `Option<&Vec<u16>>`; `None` still supplies a null pointer. The change does not alter the original process flags, handles, lifetime, environment, desktop or token policy. This mechanical review does not qualify a successor source revision.

`ACTUAL_CLIPPY.patch` is the original 656-byte patch. The exact preimage, actual postimage, forward/reverse replay audit and independent peer are included. The postimage was created as immutable Git blob `9e40662b31d10cf3231c3e69e5bcb6b258ad4248` and completely read back. No source ref was changed by this evidence work.

Both locks and both helper/sibling byte bindings remained unchanged. The original source checkout was shallow; its snapshot `parents: []` is retained verbatim and is not a claim that the source commit has no Git parent.

The job ran from **16:50:23 to 17:15:20 UTC on 2026-11-11**, inside its unchanged 65-minute job budget. This was not a timeout. There were **zero native test commands and zero model commands**. Dependency-download traffic is not counted as model traffic; physical network-request count remains unspecified.

## Offline replay

Run `python3 verify_package.py <extracted-package-directory>`. It checks all packaged bytes, ZIP/manifest identities, the original receipts and the exact one-line rewrite, without executing any archived driver or native/model command. The output must retain `qualification_passed: false`.

The earlier running-log GET returned BlobNotFound before the job ended; `RUNNING_LOG_UNAVAILABLE.json` preserves that read-only observation. It is not classified as a command failure. `original-job.log` and `JOB_LOG_TOOL_RESPONSE.json` are the later complete terminal log.

The four frozen harness inputs are complete in `harness/`. This package is not a complete repository checkout. Recovery of the plan's 20 exact source dependencies is separately indexed by `OFFLINE_SOURCE_DEPENDENCY_INPUTS.json`, immutable Git blob `b20c845bf638023bfe9f3d60116a1b9e6e546bfd`, with reader `aa6543f9825462b2efc948d4a889c0c5c430bc88` and audit `ab7d6291b0f836dccc9d0e6fc2d63aa11611e019`. That additive index selects 18 direct V16 loose members plus two V10 canonical post-format members; it does not rewrite the original preparation archives.
