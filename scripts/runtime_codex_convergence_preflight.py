#!/usr/bin/env python3
"""Align the one-shot patcher with the exact reviewed source shape."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
patcher = root / "scripts/runtime_codex_convergence.py"
content = patcher.read_text(encoding="utf-8")
old = '''    ''' + "'''fn unix_time_ms() -> Result<u64> {\n" + '''    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    Ok(u64::try_from(elapsed.as_millis())?)
}
''',
'''
new = '''    ''' + "'''fn unix_time_ms() -> Result<u64> {\n" + '''    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    u64::try_from(elapsed.as_millis()).map_err(|_| "system clock milliseconds overflow".into())
}
''',
'''
if content.count(old) != 1:
    raise SystemExit(f"expected one exact clock matcher in patcher, found {content.count(old)}")
patcher.write_text(content.replace(old, new, 1), encoding="utf-8")

diagnostic = root / "runtime_codex_patch_failure.txt"
if diagnostic.exists():
    diagnostic.unlink()

Path(__file__).unlink()
