#!/usr/bin/env python3
"""Idempotently materialize the bounded Windows/MSVC and schema-oracle repairs.

The script is intentionally fail-closed: an all-old state may be upgraded, an
all-new state may be reused, but a partially materialized state is rejected.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path.cwd()


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def count(text: str, fragment: str) -> int:
    return text.count(fragment)


def r4_is_complete() -> bool:
    patch = ROOT / "patches/rules_rust_windows_msvc_user_link_flags.patch"
    module = ROOT / "MODULE.bazel"
    runner = ROOT / ".github/scripts/run-bazel-ci.sh"
    if not (patch.is_file() and module.is_file() and runner.is_file()):
        return False
    patch_text = read(patch)
    module_text = read(module)
    runner_text = read(runner)
    return (
        'if flavor_msvc and use_direct_driver:' in patch_text
        and 'normalized_flag = "/LIBPATH:" + flag[len("-Lnative="):]' in patch_text
        and "rules_rust_windows_msvc_user_link_flags.patch" in module_text
        and "windows-msvc-host-platform" in runner_text
    )


def materialize_r4() -> None:
    if r4_is_complete():
        return
    base = Path(os.environ["BASE_MATERIALIZER"])
    if not base.is_file():
        raise SystemExit(f"base materializer not found: {base}")
    subprocess.run([os.environ.get("PYTHON", "python"), str(base)], check=True)
    if not r4_is_complete():
        raise SystemExit("r4 materializer completed without all required sentinels")


def r5_state(text: str) -> tuple[int, int, int, int]:
    return (
        count(text, "fn canonicalize_schema_sql(sql: String) -> Result<String, CognitiveStoreError>"),
        count(text, 'let canonical = sql.replace("\\r\\n", "\\n");'),
        count(text, "let canonical_sql = canonicalize_schema_sql(sql)?;"),
        count(text, "mod schema_oracle_canonicalization_tests"),
    )


def materialize_r5() -> None:
    path = ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs"
    text = read(path)
    state = r5_state(text)
    if state == (1, 1, 1, 1):
        return
    if state != (0, 0, 0, 0):
        raise SystemExit(f"partial schema-oracle portability state: {state}")

    constant_anchor = '''const REQUIRED_SCHEMA_ORACLE_SHA256: &str =
    "ae52b47126c510d36e89cf378a9df11f985527cea24111da7b2cf38b020cab6c";
'''
    helper = '''const REQUIRED_SCHEMA_ORACLE_SHA256: &str =
    "ae52b47126c510d36e89cf378a9df11f985527cea24111da7b2cf38b020cab6c";
const NON_CANONICAL_SCHEMA_CARRIAGE_RETURN: &str =
    "required cognitive schema definition contains an unsupported carriage return";

fn canonicalize_schema_sql(sql: String) -> Result<String, CognitiveStoreError> {
    if !sql.contains('\\r') {
        return Ok(sql);
    }
    let canonical = sql.replace("\\r\\n", "\\n");
    if canonical.contains('\\r') {
        return Err(CognitiveStoreError::Corrupt(
            NON_CANONICAL_SCHEMA_CARRIAGE_RETURN.to_string(),
        ));
    }
    Ok(canonical)
}
'''
    if count(text, constant_anchor) != 1:
        raise SystemExit("schema oracle constant anchor is not unique")
    text = text.replace(constant_anchor, helper, 1)

    push_anchor = "        schema_oracle_parts.push(((*name).to_string(), object_type, sql));\n"
    push_replacement = '''        let canonical_sql = canonicalize_schema_sql(sql)?;
        schema_oracle_parts.push(((*name).to_string(), object_type, canonical_sql));
'''
    if count(text, push_anchor) != 1:
        raise SystemExit("schema oracle push anchor is not unique")
    text = text.replace(push_anchor, push_replacement, 1)

    tests = '''
#[cfg(test)]
mod schema_oracle_canonicalization_tests {
    use super::CognitiveStoreError;
    use super::NON_CANONICAL_SCHEMA_CARRIAGE_RETURN;
    use super::canonicalize_schema_sql;

    #[test]
    fn canonical_schema_sql_preserves_lf_and_normalizes_crlf() {
        let lf = "CREATE TABLE example (\\n    id INTEGER PRIMARY KEY\\n)";
        let crlf = lf.replace('\\n', "\\r\\n");
        assert_eq!(
            canonicalize_schema_sql(lf.to_string()).expect("LF schema"),
            lf
        );
        assert_eq!(canonicalize_schema_sql(crlf).expect("CRLF schema"), lf);
    }

    #[test]
    fn canonical_schema_sql_rejects_bare_carriage_return() {
        let error = canonicalize_schema_sql(
            "CREATE TABLE example (\\rid INTEGER PRIMARY KEY)".to_string(),
        )
        .expect_err("bare carriage return must fail closed");
        assert!(matches!(
            error,
            CognitiveStoreError::Corrupt(ref detail)
                if detail == NON_CANONICAL_SCHEMA_CARRIAGE_RETURN
        ));
    }
}
'''
    text = text.rstrip() + "\n" + tests
    if r5_state(text) != (1, 1, 1, 1):
        raise SystemExit(f"unexpected final schema-oracle state: {r5_state(text)}")
    write(path, text)


def main() -> None:
    materialize_r4()
    materialize_r5()


if __name__ == "__main__":
    main()
