# Safe successor v6 — bounded qualification, production HOLD

The earlier complete negative evidence remains intact in the parent commits. This revision preserves the causal stack and missing-consumer investigations plus their actual fixes.

- v2 used Tagged<RawValue> at every dynamic node. With identical unoptimized compiler/input conditions, official JSON Value handled depth 64 and returned the existing budget error at 65; the adapter aborted on the default 2 MiB thread stack. The repository's existing 8 MiB stack avoided the abort but was not treated as a fix.
- v4 sends only real local tags through Serde EnumAccess. It removed the untagged-node abort but still aborted in four tagged-depth cases. v3's missing constructor field was a real compile failure and is retained.
- v5 extracts the existing large scalar-dispatch body into a separate method. A tag no longer allocates that large frame twice. All 160 separate processes (ordinary/tagged sequences and mappings, 32/48/64/65 depths, default and original repository stack sizes, old/official/fork controls) return normally. Depth 65 remains rejected under the unchanged new-parser cap.
- The actual workspace includes skills-extension metadata too: Option<u16>, Product unit enums and SkillMetadataFile. The extracted-source oracle initially found 516 differences in 2,918 observations. v6 adds the old unsigned style/range rule to u16 and preserves Product scalar/local-tag/null-payload handling. The same 2,918 observations now have zero differences.

Final v6 also preserves zero differences in the original 1,574 matrix and 28 concrete examples, 14/14 original expanded consumer tests, 13,063 structural/numeric/style/encoding/tagged-empty observations, 9/9 full-profile budget controls, and all 160 depth processes. Disabled compatibility flags still produce the official 472-difference matrix byte-for-byte. No parser, alias, input, event, scalar or depth budget was raised. This supports the bounded tested consumer types, not universal serde_yaml API equivalence.

The archive contains full stdout/stderr, exact compiler argv/input hashes, source snapshots, and patches against the pinned official package. It excludes binaries and the full upstream source tree. The new real workspace native and Bazel/dependency graph qualification is tracked separately; it remains required for production acceptance.
