# Original NDU pilot runtime source

This commit imports the **23 original Python source files** used by the recorded NDU pilot, at their original repository-relative paths. Each file is byte-for-byte identical to the `code-v3` file pinned by the original pilot plan. No runtime logic is changed in this import.

## Provenance

- Original runtime: `ndu-real-runtime-20261107-bc2efaf10cd0`, source version `code-v3`.
- Pilot plan SHA256: `139a8c0ce912f4eadb62d80463674ac7295b04fad4c455296654ec7630946880`.
- Native source-readback manifest SHA256: `7b7144d6a57b8b3fea45c37908367c9b983e7e94aa5fe8881c1c1781575b844c`.
- Source-set SHA256: `c267490a3eb14931c534588ee58deb853d5cfbb14490f099506002eebc0dbc35`.
- Base results commit: [`e2144ff750bd15b89cd5f1b8306f84298e0899fa`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e2144ff750bd15b89cd5f1b8306f84298e0899fa), from [draft PR #5321](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5321).

[`ORIGINAL_SOURCE_MANIFEST.json`](ORIGINAL_SOURCE_MANIFEST.json) records all 23 paths, exact byte counts, SHA256 values, Git blob identities, and their connection to the original pilot. Both original `__init__.py` files are included. The source was read from the original native runtime and checked against both its readback manifest and all 23 pilot-plan source pins.

## Evidence boundary

The original pilot remains **HOLD for all 24 registered contrasts**. This import supplies inspectable implementation provenance; it does not supply new experimental results, confirmation access, adoption authorization, or a completed native-owner learning loop. No experiment is launched by this publication.

Only source code and this provenance documentation are included. Raw materials, private answers, model weights, and runtime or credential configuration are outside this source import. Reproduction still depends on the separately recorded materials, split registration, isolation, artifacts, and attempt records.

The manifest describes the immutable original import. Later commits may improve future runtime behavior, with their own change and validation records, while preserving this original commit and its historical HOLD result.
