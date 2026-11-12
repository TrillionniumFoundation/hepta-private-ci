# Isolated source maintenance candidate v7

The current complete 196-file source manifest is FINAL_SOURCE_MANIFEST.json (fc153553bd244cc4f4acc0ca1120ef23696eb249). It composes the original 196 frozen source images with the 28-path / 105-operation exact receiver package 4389ac3ec9cf171f302241419c9888a0f8e765b4: 103 receiver spelling operations and two export edits introducing three crate-only type-name exports. Private fields and constructors are retained. Original source paths remain 100 replacements and 96 new paths relative to cbf6ca7dd619589be3e9e98755f185d34d0f7413.

SOURCE_MANIFEST.json and its BASE_PATH_PROOF.json preserve the earlier 196-file input snapshot; FINAL_SOURCE_MANIFEST.json records the current postimages. Both Root replay proofs independently GET/hash checked every affected full pre/post image and uniquely replayed every edit forward and backward. The two component packets are disjoint; do not apply their earlier partial packets again.

This isolated branch exists for actual formatting, lint fixes and compiler feedback. It is UNQUALIFIED. Final caller metadata is still being assembled separately, and original CALLERS is not claimed to describe the future source yet. No original full-caller, native or business PASS is asserted. The original checker/helper, seven-package / 17 Root harness and original 500 ms request budget remain unchanged. Core, AppServer and MCP component checks remain separate required work.

A successful formatter or compiler step will establish only that step. Original complete chains / positive adoption / genuine NoUpdate-or-rollback remain 0 / 0 / 0. Independent C and physical daemon-plus-Root restart remain unaccepted. Creating or updating this isolated maintenance branch does not advance Draft #6006 or merge main.
