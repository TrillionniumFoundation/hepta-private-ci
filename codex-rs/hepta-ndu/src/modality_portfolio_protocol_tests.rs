use std::io::Cursor;

use pretty_assertions::assert_eq;

use super::*;

// Independently computed with Python hashlib from domain + four raw digests.
const INITIAL: &str = "e7b489d5c98820d86aca2c7b470ff1598ba06432e735df927bfe143d647793cd";
const AFTER_IMAGE: &str = "ebdfe2754f11f7ec40f0c3dfcfa79843328f66f9fd755abdad276fa120ecb41f";
const AFTER_TEXT: &str = "d34cf00f98da2a7982b026ebdccd38450da5f2f16ea8d1913667f028a7c4ce44";
const OUTPUTS: &str = "2ba9b9c3d83a8fdbdb43745e4f5e6ea324f7de59c44001257ee39f2499e774b0";

fn init(sid: u64, mode: &str, plan: &str) -> String {
    let hashes = ["11", "22", "33", "44"].map(|s| s.repeat(32)).join("\t");
    format!(
        "MP1\tINIT\t{sid}\t2\t{}\t351232\t3584\t2\t6656\t69632\t53248\t200704\t8704\t8704\t8704\t8704\t{hashes}\t{mode}\t{plan}",
        "ab".repeat(32)
    )
}

fn choose(version: u64, joint: &str, values: [f64; 5]) -> String {
    let mut result = format!("MP1\tCHOOSE\t7\t{version}\t{joint}");
    for (i, name) in [
        "EMIT",
        "REFINE_text",
        "REFINE_audio",
        "REFINE_image",
        "REFINE_video",
    ]
    .into_iter()
    .enumerate()
    {
        let cost = if i == 0 { 330_240 } else { 8_704 };
        result.push_str(&format!("\t{name}\t{}\t{cost}", values[i]));
    }
    result
}

fn apply(current: &mut Option<SessionV1>, line: &str) -> Result<String, PortfolioError> {
    command(current, &line.split('\t').collect::<Vec<_>>())
}

#[test]
fn persistent_protocol_binds_updates_budget_outputs_and_sequence()
-> Result<(), Box<dyn std::error::Error>> {
    let hashes = ["11", "22", "55", "44"].map(|s| s.repeat(32)).join("\t");
    let next = ["66", "22", "55", "44"].map(|s| s.repeat(32)).join("\t");
    let outputs = format!(
        "text\t{}\taudio\t{}\timage\t{}\tvideo\t{}",
        "aa".repeat(32),
        "bb".repeat(32),
        "cc".repeat(32),
        "dd".repeat(32)
    );
    let emitted = format!("MP1\tEMITTED\t7\t3\t{AFTER_TEXT}\t{outputs}");
    let input = [
        init(/*sid*/ 7, "ADAPTIVE", "-"),
        choose(/*version*/ 0, INITIAL, [-3.0, -2.0, -1.5, -1.0, -2.25]),
        choose(/*version*/ 1, INITIAL, [0.0; 5]),
        format!("MP1\tREFINED\t7\t1\tREFINE_audio\t{hashes}"),
        format!("MP1\tREFINED\t7\t1\tREFINE_image\t{hashes}"),
        choose(/*version*/ 1, INITIAL, [0.0; 5]),
        choose(
            /*version*/ 1,
            AFTER_IMAGE,
            [-3.0, -0.5, -2.0, -1.0, -1.5],
        ),
        format!("MP1\tREFINED\t7\t2\tREFINE_text\t{next}"),
        choose(/*version*/ 2, AFTER_TEXT, [-0.4, 1.0, 0.0, 0.0, 0.0]),
        choose(/*version*/ 2, AFTER_TEXT, [-0.4, 0.0, 0.0, 0.0, 0.0]),
        emitted.replace("\taudio\t", "\ttext\t"),
        emitted.clone(),
        emitted,
        init(/*sid*/ 7, "CLEAN", "-"),
    ]
    .join("\n")
        + "\n";
    let mut output = Vec::new();
    run(Cursor::new(input), &mut output)?;
    let text = String::from_utf8(output)?;
    let rows = text
        .lines()
        .map(|line| line.split('\t').collect::<Vec<_>>())
        .collect::<Vec<_>>();
    assert_eq!(
        rows[0],
        vec![
            "MP1", "OK", "INIT", "7", "0", "347648", "0", "0", "0", "0", "0", "ready", INITIAL
        ]
    );
    assert_eq!(
        rows[1][3..],
        [
            "7",
            "1",
            "338944",
            "1",
            "0",
            "0",
            "1",
            "0",
            "await_refinement",
            INITIAL,
            "REFINE_image",
            "-1.00000000000000000e0"
        ]
    );
    assert_eq!(rows[2], ["MP1", "ERR", "PendingExecution"]);
    assert_eq!(rows[3], ["MP1", "ERR", "ActionMismatch"]);
    assert_eq!(rows[4][12], AFTER_IMAGE);
    assert_eq!(rows[5], ["MP1", "ERR", "SnapshotMismatch"]);
    assert_eq!(rows[6][13], "REFINE_text");
    assert_eq!(rows[7][12], AFTER_TEXT);
    assert_eq!(rows[8], ["MP1", "ERR", "NonZeroIneligible"]);
    assert_eq!(
        rows[9][3..12],
        ["7", "3", "0", "2", "1", "0", "1", "0", "await_outputs"]
    );
    assert_eq!(rows[10], ["MP1", "ERR", "InvalidOutputs"]);
    assert_eq!(
        rows[11][11..],
        [
            "sealed",
            AFTER_TEXT,
            "text",
            &"aa".repeat(32),
            "audio",
            &"bb".repeat(32),
            "image",
            &"cc".repeat(32),
            "video",
            &"dd".repeat(32),
            OUTPUTS
        ]
    );
    assert_eq!(rows[12], ["MP1", "ERR", "Sealed"]);
    assert_eq!(rows[13], ["MP1", "ERR", "SessionSequence"]);
    Ok(())
}

#[test]
fn profiles_and_committed_action_order_cannot_be_replaced() -> Result<(), PortfolioError> {
    let valid = init(/*sid*/ 7, "ADAPTIVE", "-");
    for (field, replacement) in [(5, "351233"), (6, "0"), (7, "3"), (8, "6655"), (12, "8703")] {
        let mut fields = valid.split('\t').collect::<Vec<_>>();
        fields[field] = replacement;
        let mut current = None;
        assert_eq!(
            command(&mut current, &fields),
            Err(PortfolioError::InvalidProfile)
        );
        assert_eq!(current, None);
    }
    for (mode, plan) in [
        ("CLEAN", "REFINE_text"),
        ("ADAPTIVE", "REFINE_audio"),
        ("COMMITTED", "EMIT"),
        ("COMMITTED", "REFINE_text,REFINE_audio,REFINE_video"),
    ] {
        let mut current = None;
        assert!(apply(&mut current, &init(/*sid*/ 7, mode, plan)).is_err());
        assert_eq!(current, None);
    }
    let mut current = None;
    apply(
        &mut current,
        &init(/*sid*/ 7, "COMMITTED", "REFINE_audio,REFINE_text"),
    )?;
    let before = current.clone();
    assert_eq!(
        apply(&mut current, &init(/*sid*/ 8, "ADAPTIVE", "-")),
        Err(PortfolioError::PendingExecution)
    );
    assert_eq!(
        apply(
            &mut current,
            &choose(/*version*/ 0, INITIAL, [1.0, 0.0, -2.0, 0.0, 0.0])
        ),
        Err(PortfolioError::NonZeroIneligible)
    );
    assert_eq!(current, before);
    let hashes = ["11", "22", "33", "44"].map(|s| s.repeat(32)).join("\t");
    for (version, name, values) in [
        (0, "REFINE_audio", [0.0, 0.0, -2.0, 0.0, 0.0]),
        (1, "REFINE_text", [0.0, -3.0, 0.0, 0.0, 0.0]),
    ] {
        let selected = apply(&mut current, &choose(version, INITIAL, values))?;
        assert_eq!(selected.split('\t').nth(13), Some(name));
        apply(
            &mut current,
            &format!("MP1\tREFINED\t7\t{}\t{name}\t{hashes}", version + 1),
        )?;
    }
    let selected = apply(
        &mut current,
        &choose(/*version*/ 2, INITIAL, [-4.0, 0.0, 0.0, 0.0, 0.0]),
    )?;
    assert_eq!(selected.split('\t').nth(13), Some("EMIT"));
    Ok(())
}

#[test]
fn bounded_and_unfinished_protocols_fail() {
    let mut output = Vec::new();
    assert_eq!(
        run(Cursor::new("x".repeat(4097)), &mut output)
            .err()
            .map(|e| e.kind()),
        Some(io::ErrorKind::InvalidData)
    );
    assert_eq!(output, b"MP1\tERR\tLineLimit\n");
    let input = init(/*sid*/ 7, "CLEAN", "-") + "\n";
    assert_eq!(
        run(Cursor::new(input), Vec::new()).err().map(|e| e.kind()),
        Some(io::ErrorKind::UnexpectedEof)
    );
}
