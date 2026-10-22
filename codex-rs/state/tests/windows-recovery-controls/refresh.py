"""Pin the two exact production-only reversions after repository formatting."""

import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
NATIVE = "codex-rs/utils/path-utils/src/private_state_windows_directory.rs"
IDENTITY = "codex-rs/state/src/sqlite_recovery_windows.rs"
ORIGINAL_NATIVE_SHA256 = "05f8abf49d5a0d5f099695d6138e01525ac9b5e0b369e5172e0dd8f342e2f2a6"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def mutate(lane, source):
    if lane == "shared-source":
        pattern = r"let share = FILE_SHARE_READ\s*\|\s*if is_directory\s*\{\s*FILE_SHARE_WRITE\s*\}\s*else\s*\{\s*0\s*\};"
        replacement = (
            "let share = FILE_SHARE_READ | FILE_SHARE_WRITE | "
            "windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;"
        )
        changed, count = re.subn(pattern, replacement, source)
    elif lane == "skip-snapshot":
        pattern = r"(    fn compare\(&self, lookup: &File\) -> Result<\(\), SqliteRecoveryError> \{)\n.*?\n    \}"
        match = re.search(pattern, source, re.DOTALL)
        if not match or match.group().count("!= self.snapshot") != 2:
            raise RuntimeError("snapshot comparison no longer matches the reviewed control")
        changed, count = re.subn(
            pattern, r"\1\n        let _ = (self, lookup);\n        Ok(())\n    }",
            source, flags=re.DOTALL,
        )
    else:
        raise RuntimeError("unknown control")
    if count != 1 or changed == source:
        raise RuntimeError("control must change exactly one reviewed production boundary")
    return changed


def main():
    native = (ROOT / NATIVE).read_bytes()
    original, separator, _ = native.partition(b"\n// Recovery must not create")
    if not separator or sha(original) != ORIGINAL_NATIVE_SHA256:
        raise RuntimeError("original private directory acquisition changed; independent review required")
    checker = ROOT / ".github/scripts/check_windows_private_state_acquisition.py"
    text = checker.read_text()
    text, count = re.subn(r'SOURCE_SHA256 = "[a-f0-9]{64}"', f'SOURCE_SHA256 = "{sha(native)}"', text)
    if count != 1:
        raise RuntimeError("original acquisition source pin is missing or ambiguous")
    checker.write_bytes(text.encode())
    controls = []
    for lane, path in [("shared-source", NATIVE), ("skip-snapshot", IDENTITY)]:
        data = (ROOT / path).read_bytes()
        source = data.decode()
        changed = mutate(lane, source)
        patch = f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
            source.splitlines(keepends=True), changed.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}", n=0,
        ))
        patch_path = HERE / f"{lane}.patch"
        patch_path.write_bytes(patch.encode())
        controls.append({
            "lane": lane, "production_path": path, "source_sha256": sha(data),
            "patch": patch_path.name, "patch_sha256": sha(patch.encode()),
            "mutated_sha256": sha(changed.encode()),
        })
    (HERE / "controls.json").write_bytes((json.dumps(controls, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
