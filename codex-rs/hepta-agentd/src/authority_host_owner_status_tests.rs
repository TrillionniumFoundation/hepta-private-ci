use serde_json::Value;
use serde_json::json;

use super::MAX_DIAGNOSTIC_BYTES;
use super::diagnostic;
use super::verify_status;

const VALID: &str = "Name:\tagentd\nUid:\t60002\t60002\t60002\t60002\nGroups:\t\nNoNewPrivs:\t1\nCapInh:\t0000000000000000\nCapPrm:\t0000000000000000\nCapEff:\t0000000000000000\nCapBnd:\t0000000000000000\nCapAmb:\t0000000000000000\n";

fn rejection(status: &str) -> Value {
    let error = verify_status(status, /*uid*/ 60002, /*peer_pid*/ 3).unwrap_err();
    let message = error.to_string();
    let (_, json) = message.split_once("; status_diagnostic=").unwrap();
    assert!(json.len() <= MAX_DIAGNOSTIC_BYTES);
    serde_json::from_str(json).unwrap()
}

#[test]
fn exact_owner_is_accepted_and_diagnostic_matches_the_same_buffer() {
    verify_status(VALID, /*uid*/ 60002, /*peer_pid*/ 3).unwrap();
    let value: Value =
        serde_json::from_str(&diagnostic(VALID, /*uid*/ 60002, /*peer_pid*/ 3)).unwrap();
    assert_eq!(value["pass_mask"], json!(255));
    assert_eq!(value["uid_match_mask"], json!(15));
    assert_eq!(value["status_bytes"], json!(VALID.len()));
    assert_eq!(
        value["uid"],
        json!({
            "occurrences": 1,
            "token_count": 4,
            "first_values": [60002, 60002, 60002, 60002],
        })
    );
}

#[test]
fn every_missing_required_field_is_rejected_with_its_failed_bit() {
    for (prefix, bit, sample) in [
        ("Uid:", 0, "uid"),
        ("NoNewPrivs:", 1, "no_new_privs"),
        ("CapInh:", 2, "caps"),
        ("CapPrm:", 3, "caps"),
        ("CapEff:", 4, "caps"),
        ("CapBnd:", 5, "caps"),
        ("CapAmb:", 6, "caps"),
        ("Groups:", 7, "groups"),
    ] {
        let status = VALID
            .lines()
            .filter(|line| !line.starts_with(prefix))
            .collect::<Vec<_>>()
            .join("\n");
        let value = rejection(&status);
        assert_eq!(value["pass_mask"], json!(255_u8 ^ (1 << bit)), "{prefix}");
        let field = if sample == "caps" {
            &value[sample][bit - 2]
        } else {
            &value[sample]
        };
        assert_eq!(
            field,
            &json!({
                "occurrences": 0,
                "token_count": 0,
                "first_values": [null, null, null, null],
            })
        );
    }
}

#[test]
fn each_uid_and_the_exact_four_token_width_remain_required() {
    for (replacement, uid_mask) in [
        ("Uid:\t7\t60002\t60002\t60002", 14),
        ("Uid:\t60002\t7\t60002\t60002", 13),
        ("Uid:\t60002\t60002\t7\t60002", 11),
        ("Uid:\t60002\t60002\t60002\t7", 7),
        ("Uid:\t60002\t60002\t60002", 7),
        ("Uid:\t60002\t60002\t60002\t60002\t60002", 15),
        ("Uid:\t060002\t60002\t60002\t60002", 14),
    ] {
        let status = VALID.replace("Uid:\t60002\t60002\t60002\t60002", replacement);
        let value = rejection(&status);
        assert_eq!(value["pass_mask"], json!(254), "{replacement}");
        assert_eq!(value["uid_match_mask"], json!(uid_mask), "{replacement}");
    }
}

#[test]
fn nnp_is_an_exact_line_and_normalization_does_not_authorize() {
    for replacement in [
        "NoNewPrivs:\t0",
        "NoNewPrivs: 1",
        "NoNewPrivs:\t01",
        "NoNewPrivs:\t1 ",
    ] {
        let status = VALID.replace("NoNewPrivs:\t1", replacement);
        assert_eq!(rejection(&status)["pass_mask"], json!(253));
    }
    let value = rejection(&VALID.replace("NoNewPrivs:\t1", "NoNewPrivs: 1"));
    assert_eq!(
        value["no_new_privs"]["first_values"],
        json!([1, null, null, null])
    );
}

#[test]
fn all_five_capability_sets_including_bounding_must_be_zero() {
    for (index, field) in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]
        .iter()
        .enumerate()
    {
        let status = VALID.replace(
            &format!("{field}:\t0000000000000000"),
            &format!("{field}:\t0000000000000400"),
        );
        let value = rejection(&status);
        assert_eq!(value["pass_mask"], json!(255_u8 ^ (1 << (index + 2))));
        assert_eq!(
            value["caps"][index],
            json!({
                "occurrences": 1,
                "token_count": 1,
                "first_values": [1024, null, null, null],
            })
        );
    }
}

#[test]
fn diagnostic_numeric_cap_zero_does_not_relax_exact_cap_format() {
    for replacement in [
        "CapBnd: 0000000000000000",
        "CapBnd:\t0",
        "CapBnd:\t0000000000000000 ",
    ] {
        let value = rejection(&VALID.replace("CapBnd:\t0000000000000000", replacement));
        assert_eq!(value["pass_mask"], json!(223));
        assert_eq!(
            value["caps"][3]["first_values"],
            json!([0, null, null, null])
        );
    }
}

#[test]
fn supplementary_groups_reject_and_only_four_numeric_samples_are_reported() {
    let status = VALID.replace("Groups:\t", "Groups:\t60002 7 8 9 10 11");
    let value = rejection(&status);
    assert_eq!(value["pass_mask"], json!(127));
    assert_eq!(
        value["groups"],
        json!({
            "occurrences": 1,
            "token_count": 6,
            "first_values": [60002, 7, 8, 9],
        })
    );
}

#[test]
fn duplicate_field_admission_retains_original_first_uid_and_any_other_semantics() {
    let status = format!("Uid:\t7 7 7 7\n{VALID}");
    let value = rejection(&status);
    assert_eq!(value["pass_mask"], json!(254));
    assert_eq!(value["uid"]["occurrences"], json!(2));
    // These odd duplicate inputs retain the preexisting any-exact-line rule.
    // Tightening it is a separate policy change, not a diagnostic change.
    let status = format!("NoNewPrivs:\t0\nCapBnd:\t0000000000000001\nGroups:\t7\n{VALID}");
    verify_status(&status, /*uid*/ 60002, /*peer_pid*/ 3).unwrap();
    let value: Value = serde_json::from_str(&diagnostic(
        &status, /*uid*/ 60002, /*peer_pid*/ 3,
    ))
    .unwrap();
    assert_eq!(value["pass_mask"], json!(255));
    assert_eq!(
        value["caps"][3]["first_values"],
        json!([1, null, null, null])
    );
}

#[test]
fn large_or_injected_status_text_is_never_included_and_output_has_a_hard_bound() {
    let secret = "unrelated-secret-\"\\\t\r";
    let long = "9".repeat(100_000);
    let groups = format!("{long} {}", "7 ".repeat(50_000));
    let status = VALID
        .replace(
            "Uid:\t60002\t60002\t60002\t60002",
            &format!("Uid:\t{long} {secret}"),
        )
        .replace("Groups:\t", &format!("Groups:\t{groups}"))
        .replace("CapBnd:\t0000000000000000", &format!("CapBnd:\t{long}"));
    let status = format!("{status}Name:\t{secret}\nEnvironment:\t{long}\n");
    let value = rejection(&status);
    let encoded = serde_json::to_string(&value).unwrap();
    assert!(encoded.len() <= MAX_DIAGNOSTIC_BYTES);
    assert!(!encoded.contains(secret));
    assert!(!encoded.contains("Environment"));
    assert!(!encoded.contains(&long));
    assert_eq!(value["status_bytes"], json!(status.len()));
    assert_eq!(
        value["uid"]["first_values"],
        json!([null, null, null, null])
    );
    assert_eq!(
        value["caps"][3]["first_values"],
        json!([null, null, null, null])
    );
    assert_eq!(
        value["groups"],
        json!({
            "occurrences": 1,
            "token_count": 50001,
            "first_values": [null, 7, 7, 7],
        })
    );
}

#[test]
fn maximum_numeric_samples_are_serialized_exactly_within_the_output_bound() {
    let decimal = std::array::from_fn::<_, 4, _>(|_| u64::MAX.to_string()).join(" ");
    let hex = ["ffffffffffffffff"; 4].join(" ");
    let mut status = VALID
        .replace(
            "Uid:\t60002\t60002\t60002\t60002",
            &format!("Uid:\t{decimal}"),
        )
        .replace("Groups:\t", &format!("Groups:\t{decimal}"));
    for field in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"] {
        status = status.replace(
            &format!("{field}:\t0000000000000000"),
            &format!("{field}:\t{hex}"),
        );
    }
    let value = rejection(&status);
    assert_eq!(value["pass_mask"], json!(2));
    assert_eq!(value["uid_match_mask"], json!(0));
    let expected = json!([u64::MAX, u64::MAX, u64::MAX, u64::MAX]);
    assert_eq!(value["uid"]["first_values"], expected);
    assert_eq!(value["groups"]["first_values"], expected);
    for sample in value["caps"].as_array().unwrap() {
        assert_eq!(sample["first_values"], expected);
    }
}
