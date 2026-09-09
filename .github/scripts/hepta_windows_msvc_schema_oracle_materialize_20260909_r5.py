#!/usr/bin/env python3
"""Materialize Windows/MSVC link and schema-oracle portability repairs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def run_base_materializer() -> None:
    base_value = os.environ.get("BASE_MATERIALIZER", "")
    base = Path(base_value)
    if not base.is_file():
        raise SystemExit(f"base materializer not found: {base}")
    subprocess.run([sys.executable, str(base)], check=True)


def patch_cognitive_schema_oracle() -> None:
    path = ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs"
    text = read(path)

    constant_anchor = '''const REQUIRED_SCHEMA_ORACLE_SHA256: &str =
    "ae52b47126c510d36e89cf378a9df11f985527cea24111da7b2cf38b020cab6c";
'''
    portability_helper = '''const REQUIRED_SCHEMA_ORACLE_SHA256: &str =
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
    if text.count(constant_anchor) != 1:
        raise SystemExit(
            "expected one cognitive schema oracle constant anchor, found "
            f"{text.count(constant_anchor)}"
        )
    text = text.replace(constant_anchor, portability_helper, 1)

    push_anchor = (
        "        schema_oracle_parts.push(((*name).to_string(), object_type, sql));\n"
    )
    push_replacement = '''        let canonical_sql = canonicalize_schema_sql(sql)?;
        schema_oracle_parts.push(((*name).to_string(), object_type, canonical_sql));
'''
    if text.count(push_anchor) != 1:
        raise SystemExit(
            "expected one cognitive schema oracle push anchor, found "
            f"{text.count(push_anchor)}"
        )
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
    if "mod schema_oracle_canonicalization_tests" in text:
        raise SystemExit("schema oracle canonicalization tests already exist")
    text = text.rstrip() + "\n" + tests

    expected_fragments = {
        "fn canonicalize_schema_sql(sql: String) -> Result<String, CognitiveStoreError>": 1,
        'let canonical = sql.replace("\\r\\n", "\\n");': 1,
        "let canonical_sql = canonicalize_schema_sql(sql)?;": 1,
        "mod schema_oracle_canonicalization_tests": 1,
    }
    for fragment, expected_count in expected_fragments.items():
        observed_count = text.count(fragment)
        if observed_count != expected_count:
            raise SystemExit(
                f"cognitive schema fragment count mismatch: {fragment}: "
                f"expected {expected_count}, observed {observed_count}"
            )

    write(path, text)


def main() -> None:
    run_base_materializer()
    patch_cognitive_schema_oracle()


if __name__ == "__main__":
    main()
