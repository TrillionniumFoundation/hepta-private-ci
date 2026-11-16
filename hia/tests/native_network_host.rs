// The runner prepends the complete pinned original function and actual adapter.
include!("network_host_fixtures.rs");

network_host_owner!(reference, original);
network_host_owner!(native, candidate);

fn compare(raw: &str) {
    let expected =
        original_owner::normalize_network_rule_host(raw).map_err(|error| error.to_string());
    let actual = hia_native_network_host::normalize(raw).map_err(|error| error.to_string());
    assert_eq!(
        actual, expected,
        "direct complete-owner mismatch for {raw:?}"
    );
    assert_eq!(
        native::direct(raw, Some("理由\0metadata")),
        reference::direct(raw, Some("理由\0metadata"))
    );
}

fn reset_file(path: &std::path::Path, seed: Option<&[u8]>) {
    let parent = path
        .parent()
        .unwrap_or_else(|| panic!("fixture path has no parent"));
    if path.exists() {
        std::fs::remove_file(path)
            .unwrap_or_else(|error| panic!("remove owned fixture file: {error}"));
    }
    if parent.exists() {
        std::fs::remove_dir(parent)
            .unwrap_or_else(|error| panic!("remove empty fixture directory: {error}"));
    }
    if let Some(seed) = seed {
        std::fs::create_dir(parent)
            .unwrap_or_else(|error| panic!("create fixture directory: {error}"));
        std::fs::write(path, seed).unwrap_or_else(|error| panic!("seed fixture file: {error}"));
    }
}

fn main() {
    let directory = std::path::PathBuf::from(
        std::env::args()
            .nth(1)
            .unwrap_or_else(|| panic!("a new owned artifact directory is required")),
    );
    assert!(directory.is_dir());
    let literal = [
        ("Api.Example.COM.:443", "api.example.com"),
        ("[AbC. ]:80", "abc."),
        ("[. ]", "."),
        ("a. :80", "a."),
        ("ÄBC", "Äbc"),
        ("a\0b", "a\0b"),
        ("[::1]:999999", "::1"),
        ("a:abc", "a:abc"),
        (":123", ":123"),
        ("a:b:c", "a:b:c"),
        ("\u{1c}A\u{1f}", "\u{1c}a\u{1f}"),
    ];
    let mut compared = 0_usize;
    for (raw, expected) in literal {
        assert_eq!(
            original_owner::normalize_network_rule_host(raw)
                .unwrap_or_else(|error| panic!("original literal fixture failed: {error}")),
            expected
        );
        compare(raw);
        compared += 1;
    }
    let alphabet = ['a', ':', '.', ' ', '[', ']', '/', '*', '0'];
    let mut enumerated = 0_usize;
    for length in 0..=4_u32 {
        for value in 0..alphabet.len().pow(length) {
            let mut digits = value;
            let mut raw = String::new();
            for _ in 0..length {
                raw.push(alphabet[digits % alphabet.len()]);
                digits /= alphabet.len();
            }
            compare(&raw);
            enumerated += 1;
        }
    }
    compared += enumerated;
    let mut unicode_cases = 0_usize;
    for point in (0..=0x00a1)
        .chain(0x167e..=0x1682)
        .chain(0x1ffe..=0x200d)
        .chain(0x2026..=0x2031)
        .chain(0x205e..=0x2061)
        .chain(0x2ffe..=0x3002)
        .chain([0x180e, 0xfeff, 0x10ffff])
    {
        let value = char::from_u32(point).unwrap_or_else(|| panic!("invalid scalar fixture"));
        for raw in [
            value.to_string(),
            format!("{value}A.{value}"),
            format!("A{value}B"),
            format!("[{value}A. {value}]:80"),
        ] {
            compare(&raw);
            unicode_cases += 1;
        }
    }
    compared += unicode_cases;
    let choices = [
        'A', 'z', '0', '9', ':', '.', ' ', '[', ']', '/', '?', '#', '*', '\0', '\t', '\r', '\n',
        'Ä', 'é', '中', '😀', '\u{85}', '\u{a0}', '\u{2003}', '\u{200b}', '\u{feff}',
    ];
    let mut state = 0x17_0de_u64;
    for _ in 0..1024 {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        let length = state as usize % 81;
        let mut raw = String::new();
        for _ in 0..length {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            raw.push(choices[state as usize % choices.len()]);
        }
        compare(&raw);
        compared += 1;
    }
    let samples = host_samples();
    for (_, raw) in &samples {
        compare(raw);
        compared += 1;
    }
    let mut entry_cases = 0;
    for raw in [
        "EXAMPLE.COM.:443",
        "[AbC. ]:80",
        "ÄBC",
        "a\0b",
        "[a]oops",
        "http://bad",
        "a* b",
        "a b",
        "",
        "[ .]",
    ] {
        for justification in [None, Some(""), Some(" \u{2003}"), Some("理由\0metadata")] {
            assert_eq!(
                native::direct(raw, justification),
                reference::direct(raw, justification)
            );
            entry_cases += 1;
            for protocol in [
                "http",
                "https",
                "https_connect",
                "http-connect",
                "socks5_tcp",
                "socks5_udp",
                "bad",
            ] {
                for decision in ["allow", "deny", "prompt", "bad"] {
                    assert_eq!(
                        native::parse(raw, protocol, decision, justification),
                        reference::parse(raw, protocol, decision, justification)
                    );
                    entry_cases += 1;
                }
            }
            for seed in [
                None,
                Some(b"# seed\r\n".as_slice()),
                Some(b"# seed".as_slice()),
            ] {
                let path = directory.join("amend-fixture").join("policy.rules");
                reset_file(&path, seed);
                let expected = reference::amend(&path, raw, justification);
                reset_file(&path, seed);
                let actual = native::amend(&path, raw, justification);
                assert_eq!(actual, expected);
                entry_cases += 1;
            }
        }
    }
    let direct_error = native::direct("http://bad", Some(" "));
    assert!(
        direct_error["result"]["Err"]["display"]
            .as_str()
            .unwrap_or_else(|| panic!("missing direct error"))
            .contains("without scheme or path")
    );
    let parser_error = native::parse("http://bad", "https", "allow", Some(" "));
    assert!(
        parser_error["result"]["Err"]["display"]
            .as_str()
            .unwrap_or_else(|| panic!("missing parser error"))
            .contains("justification cannot be empty")
    );
    let suffix = hia_native_network_host::normalize(" [a]oops ")
        .expect_err("suffix must be rejected")
        .to_string();
    assert_eq!(
        suffix,
        "invalid rule: network_rule host contains an unsupported suffix:  [a]oops "
    );
    let huge_ignored = format!("http://{}", "A".repeat(2_097_153));
    assert_eq!(
        native::parse(&huge_ignored, "bad", "bad", Some(" ")),
        reference::parse(&huge_ignored, "bad", "bad", Some(" "))
    );
    entry_cases += 1;
    let threads = (0..8)
        .map(|worker| {
            std::thread::spawn(move || {
                for index in 0..32 {
                    compare(&format!(" \u{2003}[ABC.{worker}.{index}]:999999\u{85}"));
                }
                32_usize
            })
        })
        .collect::<Vec<_>>();
    let concurrent = threads
        .into_iter()
        .map(|thread| {
            thread
                .join()
                .unwrap_or_else(|_| panic!("concurrent normalization failed"))
        })
        .sum::<usize>();
    compared += concurrent;
    println!(
        "network_host_public={}",
        serde_json::json!({"passed": true,
        "complete_owner_comparisons": compared, "enumerated_hosts": enumerated,
        "unicode_hosts": unicode_cases, "public_entry_observations": entry_cases,
        "concurrent_comparisons_included": concurrent, "skipped": 0,
        "performance_qualified": false, "whole_policy_migrated": false})
    );
}
