#!/usr/bin/env python3
"""Prepare a small oracle for the actual rollout conversion, outside the workspace.

The legacy Chrono dependency exists only in this differential qualification.
Neither a production manifest nor either production dependency lock is changed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    source = root / "codex-rs/rollout/src/list.rs"
    text = source.read_text()
    match = re.search(
        r"^impl From<codex_state::Anchor> for Cursor \{.*?^\}", text, re.M | re.S
    )
    if match is None:
        raise SystemExit("actual Cursor conversion was not found")
    implementation = match.group()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "Cargo.toml").write_text(
        """[package]
name = "rollout-nanosecond-boundary-oracle"
version = "0.1.0"
edition = "2024"

[dependencies]
chrono = { version = "=0.4.43", default-features = false, features = ["std"] }
jiff = "=1.0.3"
time = { version = "=0.3.55", features = ["formatting", "parsing", "large-dates"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
pretty_assertions = "1"

[lib]
name = "codex_utils_time"
path = """
        + json.dumps(str(root / "codex-rs/utils/time/src/lib.rs"))
        + """

[[test]]
name = "cursor_boundary"
path = "cursor_boundary.rs"

[profile.dev]
debug = 0
incremental = false
"""
    )
    shutil.copyfile(Path(__file__).with_name("oracle.Cargo.lock"), output / "Cargo.lock")
    prelude = """use codex_utils_time::Timestamp;
use time::OffsetDateTime;

// Only the unrelated thread-id type is reduced to an opaque copyable value.
// The production conversion below is copied verbatim from the qualified tree.
mod codex_state {
    pub struct Anchor {
        pub ts: codex_utils_time::Timestamp,
        pub id: Option<u128>,
    }
}
struct Cursor {
    ts: OffsetDateTime,
    id: Option<u128>,
}
"""
    tests = """
#[test]
fn actual_cursor_conversion_matches_chrono_0_4_43() {
    let mut cases = Vec::new();
    let seconds = [
        chrono::DateTime::<chrono::Utc>::MIN_UTC.timestamp(),
        -9_223_372_039, -9_223_372_038, -9_223_372_037, -9_223_372_036,
        -9_223_372_035, -61, -60, -59, -1, 0, 1, 59, 60, 61,
        1_483_228_799, 1_767_225_600, 9_223_372_035, 9_223_372_036,
        9_223_372_037, 9_223_372_038,
        chrono::DateTime::<chrono::Utc>::MAX_UTC.timestamp(),
    ];
    let fractions = [
        0, 1, 145_224_191, 145_224_192, 145_224_193, 499_999_999,
        500_000_000, 854_775_807, 854_775_808, 999_999_999,
        1_000_000_000, 1_000_000_001, 1_500_000_000, 1_999_999_999,
    ];
    for second in seconds {
        for fraction in fractions {
            cases.push((second, fraction));
        }
    }
    let mut random = 0x83f0_426a_11b6_9d13_u64;
    for _ in 0..512 {
        random = random.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
        let nanos = random as i64;
        cases.push((nanos.div_euclid(1_000_000_000), nanos.rem_euclid(1_000_000_000) as u32));
    }
    for limit in [i128::from(i64::MIN), i128::from(i64::MAX)] {
        for adjustment in -64..=64 {
            let nanos = limit + adjustment;
            cases.push((nanos.div_euclid(1_000_000_000) as i64, nanos.rem_euclid(1_000_000_000) as u32));
        }
    }
    let mut accepted = 0;
    let mut rejected = 0;
    let mut epoch_fallbacks = 0;
    let mut leap_seconds = 0;
    for (seconds, nanos) in cases {
        let old = chrono::DateTime::<chrono::Utc>::from_timestamp(seconds, nanos);
        let new = Timestamp::from_parts(seconds, nanos);
        assert_eq!(old.is_some(), new.is_some(), "constructor {seconds}/{nanos}");
        let (Some(old), Some(new)) = (old, new) else {
            rejected += 1;
            continue;
        };
        accepted += 1;
        leap_seconds += usize::from(nanos >= 1_000_000_000);
        let legacy_nanos = old.timestamp_nanos_opt();
        epoch_fallbacks += usize::from(legacy_nanos.is_none());
        let expected = legacy_nanos
            .and_then(|nanos| OffsetDateTime::from_unix_timestamp_nanos(i128::from(nanos)).ok())
            .unwrap_or(OffsetDateTime::UNIX_EPOCH);
        for id in [None, Some(0x123)] {
            let actual = Cursor::from(codex_state::Anchor { ts: new, id });
            assert_eq!((actual.ts, actual.id), (expected, id), "conversion {seconds}/{nanos}");
        }
    }
    println!("{}", serde_json::json!({
        "legacy": "chrono=0.4.43", "accepted_instants": accepted,
        "rejected_parts": rejected, "epoch_fallbacks": epoch_fallbacks,
        "represented_leap_seconds": leap_seconds,
        "cursor_comparisons": accepted * 2, "mismatches": 0
    }));
}
"""
    (output / "cursor_boundary.rs").write_text(prelude + implementation + tests)
    # The full workspace's package-specific overrides cannot name packages that
    # are absent from this isolated graph. Preserve its default timeout/retry
    # policy without claiming that the oracle runs those other packages.
    (output / "nextest.toml").write_text(
        '[profile.default]\n'
        'slow-timeout = { period = "30s", terminate-after = 2 }\n'
        'retries = 1\n\n'
        '[profile.default.junit]\npath = "junit.xml"\n\n'
        '[profile.local]\ninherits = "default"\n'
    )
    receipt = {
        "production_source": str(source.relative_to(root)),
        "production_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "conversion_sha256": hashlib.sha256(implementation.encode()).hexdigest(),
        "actual_time_source": "codex-rs/utils/time/src/lib.rs",
        "scope": "actual conversion and time source; opaque id fixture; not full rollout build",
    }
    (output / "source-binding.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
