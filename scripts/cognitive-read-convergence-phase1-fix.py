from pathlib import Path

path = Path("codex-rs/hepta-cognitive-read/src/ids_tests.rs")
text = path.read_text()
start = text.index("fn duplicate_fields_invalid_budgets_and_snapshot_mismatch_fail_closed()")
end = text.index("\n#[test]", start)
block = text[start:end]
old = block
block = block.replace("let snapshot = snapshot(", "let base_snapshot = snapshot(", 1)
block = block.replace("snapshot.snapshot_digest", "base_snapshot.snapshot_digest")
block = block.replace("read_ids_v1(&snapshot,", "read_ids_v1(&base_snapshot,")
if block == old:
    raise SystemExit("phase-one shadowing correction did not apply")
path.write_text(text[:start] + block + text[end:])
