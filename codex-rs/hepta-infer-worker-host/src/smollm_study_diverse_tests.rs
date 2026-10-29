//! Fixed public training inputs and a fresh, fully excluded V3 study cohort.
use super::*;
use pretty_assertions::assert_eq;

pub(super) const DATA_SHA: &str =
    "d457f4b01cc6aaa445403e81b1fa9511e24f23e4254a6ef9ff9ec29abab693cf";
pub(super) const EXCLUSION_SHA: &str =
    "946d33b8f3cd95949f8eaf3623948639cf68c58214ad8b8f191ae0c2088606e4";
pub(super) const OBJECTIVE: &str = "hepta-real-neural-study-diverse-v3:original-parent:thirty-updates-ten-row-binary-CE:300-exposures-60-distinct-public-rows:exclude-all-known-through-a593:future-two-windows:256-numeric-256-uppercase-each:final-holdout-512:ips-correctness:alpha-50000:superiority-0:observed-family-retention";

pub(super) fn training_rows() -> TestResult<Vec<Value>> {
    let raw = include_bytes!("../fixtures/smollm-diverse60-training-v3.json");
    if Digest32::of_bytes(raw).to_string() != DATA_SHA {
        return Err("fixed diverse training bytes changed".into());
    }
    let data: Value = serde_json::from_slice(raw)?;
    let rows = data["training_rows"]
        .as_array()
        .ok_or("diverse training rows")?;
    if data["schema"] != "llm-binary-diverse60-training-data-v3"
        || rows.len() != 60
        || data["expected_input_tokens"] != 15_600
    {
        return Err("exact sixty-row public training contract required".into());
    }
    Ok(rows.clone())
}

pub(super) fn excluded_prompts() -> TestResult<std::collections::BTreeSet<String>> {
    let raw = include_bytes!("../fixtures/smollm-consumed-prompts-all-through-a593-v3.json");
    if Digest32::of_bytes(raw).to_string() != EXCLUSION_SHA {
        return Err("complete frozen prompt exclusions changed".into());
    }
    let value: Value = serde_json::from_slice(raw)?;
    let hashes = value["excluded_prompt_sha256"]
        .as_array()
        .ok_or("excluded prompts")?;
    let mut excluded = std::collections::BTreeSet::new();
    let mut previous = "";
    for hash in hashes {
        let hash = hash.as_str().ok_or("excluded prompt digest")?;
        if hash.len() != 64
            || !hash
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            || hash <= previous
            || !excluded.insert(hash.to_owned())
        {
            return Err("ordered unique lowercase prompt digests required".into());
        }
        previous = hash;
    }
    if value["schema"] != "hepta-neural-consumed-prompt-exclusion-v3"
        || value["unique_consumed_prompts"] != 10_382
        || excluded.len() != 10_382
        || value["labels_or_scores_included"] != false
        || value["new_holdout_generated"] != false
        || value["qualification"] != false
    {
        return Err("complete hash-only known exposure contract required".into());
    }
    for row in training_rows()? {
        if !excluded.contains(
            row["prompt_sha256"]
                .as_str()
                .ok_or("training prompt digest")?,
        ) {
            return Err("all current training prompts must be excluded".into());
        }
    }
    Ok(excluded)
}

pub(super) fn declaration(value: &mut Value) -> TestResult<()> {
    excluded_prompts()?;
    value["schema"] = json!("hepta-neural-study-diverse-v3-preregistered");
    value["optimizer_steps"] = json!(30);
    value["actual_row_exposures"] = json!(300);
    value["distinct_source_rows"] = json!(60);
    value["physical_microbatch"] = json!(1);
    value["expected_input_tokens"] = json!(15_600);
    value["fixed_training_data_sha256"] = json!(DATA_SHA);
    value["recipe"] = json!(
        "fixed-AdamW-0.002-zero-decay-thirty-updates-six-ten-row-batches-five-passes-scalar-original-yes-no-CE-no-EOS"
    );
    value["disclosed_adaptive_followup_to_known_NoGain"] = json!(true);
    value["previous_consumed_prompt_exclusion_sha256"] = json!(EXCLUSION_SHA);
    value["training_provenance"] = json!(
        "sixty fixed public training rows and 120 authenticated ledger records; thirty updates and 300 scalar gradient exposures; original parent material plan remains ten steps; distinct prompts are not independent semantic operations"
    );
    value["task_rule"] = json!(
        "original 100..9998 adjacent integers and original four uppercase words; fresh random seed and V3 domain; exclude all 10382 known training/development/formal prompt hashes; each family balanced yes/no; no outcome-based resampling"
    );
    Ok(())
}

pub(super) fn tasks(seed: &[u8; 32], yes: &StableId, actions: &[StableId; 2]) -> TestResult<Value> {
    let excluded = excluded_prompts()?;
    let no = actions
        .iter()
        .find(|value| *value != yes)
        .ok_or("no action")?;
    let mut used = std::collections::BTreeSet::new();
    let mut windows = Vec::new();
    for window in 0_u64..2 {
        let mut rows = Vec::new();
        for index in 0_u64..512 {
            let hash = Digest32::of_parts(&[
                b"hepta.neural.study.diverse60.two-families.v3\0",
                seed,
                &window.to_be_bytes(),
                &index.to_be_bytes(),
            ]);
            let bytes = hash.as_array();
            let mut number = 100 + u64::from_be_bytes(bytes[..8].try_into()?) % 9_899;
            let expected = if index.is_multiple_of(2) { no } else { yes };
            let mut selected = None;
            for _ in 0..9_899 {
                let (family, prompt) = if index < 256 {
                    let (left, right) = if expected == yes {
                        (number + 1, number)
                    } else {
                        (number, number + 1)
                    };
                    (
                        "integer-comparison",
                        format!("Answer with only yes or no. Is {left} greater than {right}?"),
                    )
                } else {
                    let words = if expected == yes {
                        ["Alpha", "Gamma"]
                    } else {
                        ["beta", "delta"]
                    };
                    let word = words[usize::from(bytes[8] & 1)];
                    (
                        "uppercase",
                        format!(
                            "Answer with only yes or no. Does the first character of {word} use uppercase? Item {number}."
                        ),
                    )
                };
                let prompt_digest = Digest32::of_bytes(prompt.as_bytes()).to_string();
                if !used.contains(&number) && !excluded.contains(&prompt_digest) {
                    used.insert(number);
                    selected = Some((family, prompt));
                    break;
                }
                number = 100 + (number - 99) % 9_899;
            }
            let (family, prompt) = selected.ok_or("unseen original task support exhausted")?;
            rows.push(json!({"id":format!("future-{window}-{index}"),"family":family,"prompt":prompt,
                "expected":expected.as_str(),"principal":format!("future-sample-{window}-{index}"),
                "episode":format!("future-episode-{window}-{index}"),"cluster":format!("future-cluster-{window}-{index}")}));
        }
        windows.push(rows);
    }
    Ok(json!(windows))
}

#[test]
fn diverse_future_cohort_excludes_all_known_prompts_with_original_family_balance() -> TestResult<()>
{
    let yes = id("yes");
    let actions = [yes.clone(), id("no")];
    let windows = tasks(&[7; 32], &yes, &actions)?;
    let excluded = excluded_prompts()?;
    let mut observed = std::collections::BTreeSet::new();
    for window in windows.as_array().ok_or("windows")? {
        let rows = window.as_array().ok_or("rows")?;
        assert_eq!(rows.len(), 512);
        for family in ["integer-comparison", "uppercase"] {
            for action in &actions {
                assert_eq!(
                    rows.iter()
                        .filter(|row| row["family"] == family && row["expected"] == action.as_str())
                        .count(),
                    128
                );
            }
        }
        for row in rows {
            let prompt = row["prompt"].as_str().ok_or("prompt")?;
            let hash = Digest32::of_bytes(prompt.as_bytes()).to_string();
            assert!(!excluded.contains(&hash));
            assert!(observed.insert(hash));
        }
    }
    assert_eq!(observed.len(), 1024);
    Ok(())
}
