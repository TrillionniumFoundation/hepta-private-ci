from pathlib import Path

path = Path("apps/hepta-browser/servo-worker/src/main.rs")
text = path.read_text(encoding="utf-8")
needle = "OperationBinding::DocumentAction { source, action } => {"
replacement = "OperationBinding::DocumentAction { ref source, action } => {"
count = text.count(needle)
if count != 1:
    raise SystemExit(
        f"expected exactly one generated DocumentAction match arm, found {count}"
    )
path.write_text(text.replace(needle, replacement), encoding="utf-8")
