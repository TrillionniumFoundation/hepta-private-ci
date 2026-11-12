# V44: store the original source evidence as text

This candidate renames the original evidence copy from `FORMATTED_SOURCE.rs` to `FORMATTED_SOURCE.rs.txt` with byte-identical content. The product Rust, all CALLERS rules, formatter, checker, typed helper and original harness are unchanged. No new exclusion is introduced. The complete original V43 artifact-formatting failure is retained under `native-components-314fafc-seven/v18`.

V41 and V42 failure history remains intact. Full source qualification must run at this new fixed tree; ordinary business counts remain **0 / 0 / 0**, independent C and physical daemon/Root restart remain unaccepted. Draft only.
