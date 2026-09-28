#!/usr/bin/env python3
"""Apply the reviewed seven-file repair for native run 36366750911."""

from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
base = root / "codex-rs/hepta-evidence/src"


def edit(name, old, new, count=1):
    path = base / name
    text = path.read_text()
    observed = text.count(old)
    if observed != count:
        raise SystemExit(f"{name}: expected {count} matches, found {observed}")
    path.write_text(text.replace(old, new))


q = base / "qualification.rs"
text = q.read_text()
match = re.search(r'pub\(crate\) const QUALIFICATION_COLUMNS: &str =\s*"([^"]+)";', text)
if not match:
    raise SystemExit("missing exact static column inventory")
columns = match[1]
macro = '''// A literal-only suffix keeps every production statement statically SQL-safe.
// Caller-controlled values are supplied exclusively through bind parameters.
macro_rules! qualification_select {
    ($suffix:literal) => {
        concat!(
            "SELECT ''' + columns + ''' FROM qualification_evidence ",
            $suffix
        )
    };
}
pub(crate) use qualification_select;'''
text = text[:match.start()] + macro + text[match.end():]
pattern = r'sqlx::query\(&format!\(\s*"SELECT \{QUALIFICATION_COLUMNS\} FROM qualification_evidence\s+([^"]+)"\s*\)\)'
text, count = re.subn(pattern, lambda m: 'sqlx::query(qualification_select!("' + m[1] + '"))', text)
if count != 4:
    raise SystemExit(f"qualification SQL inventory {count}")
q.write_text(text)

path = base / "qualification_paging.rs"
text = path.read_text().replace("use crate::qualification::QUALIFICATION_COLUMNS;", "use crate::qualification::qualification_select;")
text, count = re.subn(pattern, lambda m: 'sqlx::query(qualification_select!("' + m[1] + '"))', text)
if count != 1:
    raise SystemExit("paging SQL inventory")
path.write_text(text)

path = base / "qualification_commitment.rs"
text = path.read_text().replace("use crate::qualification::QUALIFICATION_COLUMNS;", "use crate::qualification::qualification_select;")
text, count = re.subn(r'let statement = format!\(\s*"SELECT \{QUALIFICATION_COLUMNS\} FROM qualification_evidence WHERE evidence_id = \?"\s*\);', 'let statement = qualification_select!("WHERE evidence_id = ?");', text)
if count != 1:
    raise SystemExit("commitment SQL inventory")
path.write_text(text.replace("sqlx::query(&statement)", "sqlx::query(statement)"))

path = base / "recovery_snapshot.rs"
text = path.read_text().replace("use crate::qualification::QUALIFICATION_COLUMNS;", "use crate::qualification::qualification_select;")
text, count = re.subn(r'let columns = match domain \{.*?\n    \};\n    let statement = format!\(.*?\n    \);', '''let statement = match domain {
        Domain::LegacyEnvelope => "SELECT seq, evidence_id, envelope_sha256 FROM qualification_evidence WHERE seq > ? ORDER BY seq ASC LIMIT ?",
        Domain::AuthenticatedAdmission => qualification_select!("WHERE seq > ? ORDER BY seq ASC LIMIT ?"),
    };''', text, count=1, flags=re.S)
if count != 1:
    raise SystemExit("recovery SQL inventory")
path.write_text(text.replace("sqlx::query(&statement)", "sqlx::query(statement)"))

edit(Path("store/runtime.rs"), "statement: &str", "statement: &'static str")
path = base / "store/runtime.rs"
text = path.read_text()
old = '''        let configured_limit: i64 =
            sqlx::query_scalar(&format!("PRAGMA max_page_count = {requested_limit}"))
                .fetch_one(&store.pool)
                .await
                .expect("install disk-full injection ceiling");'''
new = '''        // SQLite does not bind PRAGMA assignment values. This test-only fragment
        // is constructed solely from a checked positive i64, never caller text.
        let mut pragma = sqlx::QueryBuilder::<sqlx::Sqlite>::new("PRAGMA max_page_count = ");
        pragma.push(requested_limit);
        let configured_limit: i64 = pragma
            .build_query_scalar()
            .fetch_one(&store.pool)
            .await
            .expect("install disk-full injection ceiling");'''
if text.count(old) != 1:
    raise SystemExit("fault injection SQL changed")
path.write_text(text.replace(old, new))

edit(Path("frontier_backend_file/segmented/tests.rs"), "            Self {\n                _external: external,", "            let local_root = local.path().canonicalize().unwrap();\n            Self {\n                _external: external,")
edit(Path("frontier_backend_file/segmented/tests.rs"), "local_root: local.path().canonicalize().unwrap(),", "local_root,")
path = base / "frontier_backend_file/segmented/tests.rs"
text, count = re.subn(r"for generation in 1\.\.=([56]) \{", r"for generation in 1_u64..=\1 {", path.read_text())
if count != 3:
    raise SystemExit(f"generation loops changed: {count}")
path.write_text(text)

edit("qualification_paging_tests.rs", "super::decode_reference", "super::checked_qualification_reference")
path = base / "qualification_paging_tests.rs"
text = path.read_text()
start = text.index('        "SELECT seq, evidence_id, candidate_id, source_commit, source_tree,', text.index("let forged_digest"))
end = text.index(' WHERE evidence_id = ?",', start) + len(' WHERE evidence_id = ?",')
select = '        "SELECT ' + columns.replace("payload_sha256,", "? AS payload_sha256,") + ' FROM qualification_evidence WHERE evidence_id = ?",'
path.write_text(text[:start] + select + text[end:])

for name in ("qualification.rs", "qualification_commitment.rs", "qualification_paging.rs", "recovery_snapshot.rs"):
    if "QUALIFICATION_COLUMNS" in (base / name).read_text():
        raise SystemExit(f"unconverted dynamic column reference: {name}")
print("Applied seven-file native compilation repair; no production SQL opt-out or weakened assertion.")
