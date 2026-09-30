#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re


def replace_regex_once(path: Path, pattern: re.Pattern[str], replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"{path}: expected one {label}, found {count}")
    path.write_text(updated, encoding="utf-8")


tests_path = Path("codex-rs/hepta-infer-core/src/native_control_tests.rs")
for output_name in ("observed", "old_output"):
    replace_regex_once(
        tests_path,
        re.compile(
            rf'''let event = Event::Observe \{{\s*
\s*request_id:\s*"r1"\.to_string\(\),\s*
\s*output:\s*{output_name},\s*
\s*\}};''',
            re.MULTILINE,
        ),
        f'''let event = Event::Observe {{
        request_id: "r1".to_string(),
        output: {output_name},
        observed_at_unix_ms: 0,
        usage_units: None,
    }};''',
        f"historical {output_name} Observe fixture",
    )

replace_regex_once(
    tests_path,
    re.compile(
        r'''(?m)^(    let mut json = serde_json::to_value\(event\)\.unwrap\(\);\n)(    json\["Observe"\]\["output"\])'''
    ),
    '''\g<1>    json["Observe"]
        .as_object_mut()
        .unwrap()
        .remove("observed_at_unix_ms");
    json["Observe"]
        .as_object_mut()
        .unwrap()
        .remove("usage_units");
\g<2>''',
    "legacy Observe JSON projection",
)

native_path = Path("codex-rs/hepta-infer-core/src/native_control.rs")
replace_regex_once(
    native_path,
    re.compile(
        r'''(?m)(        if record\.observation\.as_ref\(\) == Some\(&output\)\n            && usage_units\.is_none_or\(\|usage\| record\.observed_usage_units == Some\(usage\)\))(\n        \{)'''
    ),
    '''\g<1>
            && record.last_observed_at_unix_ms == Some(observed_at_unix_ms)\g<2>''',
    "observation idempotency condition",
)
