/*
 * Copyright 2018 The Starlark in Rust Authors.
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

use std::env;
use std::fmt::Write;
use std::fs;

use anyhow::Context;

const REGENERATE_VAR_NAME: &str = "STARLARK_RUST_REGENERATE_GOLDEN_TESTS";

#[allow(clippy::write_literal)] // We mark generated files as generated, but not this file.
fn make_golden(output: &str) -> String {
    let mut golden = String::new();
    writeln!(golden, "# {at}generated", at = "@").unwrap();
    writeln!(golden, "# To regenerate, run:").unwrap();
    writeln!(golden, "# ```").unwrap();
    writeln!(
        golden,
        // TODO(nga): fix instruction for `starlark_syntax` crate.
        "# {REGENERATE_VAR_NAME}=1 cargo test -p starlark --lib"
    )
    .unwrap();
    writeln!(golden, "# ```").unwrap();
    writeln!(golden).unwrap();
    writeln!(golden, "{}", output.trim_end()).unwrap();
    golden
}

/// Common code for golden tests.
pub fn golden_test_template(golden_rel_path: &str, output: &str) {
    assert!(golden_rel_path.starts_with("src/"));
    assert!(golden_rel_path.contains(".golden"));

    let manifest_dir =
        env::var("CARGO_MANIFEST_DIR").expect("`CARGO_MANIFEST_DIR` variable must be set");

    let golden_file_path = format!("{manifest_dir}/{golden_rel_path}");

    let output_with_prefix = make_golden(output);

    // Select the explicit JSON representation only for fixtures stored in that
    // form. The decoded string still contains every original whitespace byte.
    let json_golden_file_path = format!("{golden_file_path}.json");
    let encoded = fs::exists(&json_golden_file_path)
        .with_context(|| format!("Finding `{json_golden_file_path}`"))
        .unwrap();
    let path = if encoded {
        &json_golden_file_path
    } else {
        &golden_file_path
    };

    if env::var(REGENERATE_VAR_NAME).is_ok() {
        let payload = if encoded {
            serde_json::to_string(&output_with_prefix).unwrap() + "\n"
        } else {
            output_with_prefix
        };
        fs::write(path, payload)
            .with_context(|| format!("Writing `{path}`"))
            .unwrap();
    } else {
        let mut expected = fs::read_to_string(path)
            .with_context(|| format!("Reading `{path}`"))
            .unwrap();
        if encoded {
            expected = serde_json::from_str(&expected)
                .with_context(|| format!("Decoding `{path}`"))
                .unwrap();
        }

        let expected = if cfg!(windows) {
            // Git may check out files on Windows with \r\n as line separator.
            // We could configure git, but it's more reliable to handle it in the test.
            expected.replace("\r\n", "\n")
        } else {
            expected
        };
        assert_eq!(expected, output_with_prefix);
    }
}
