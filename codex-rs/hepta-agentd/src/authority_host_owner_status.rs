//! Bounded diagnostics from the exact status buffer used for owner admission.
//!
//! These values explain a rejection only. Parsed/normalized diagnostic values never
//! participate in admission, and no process file is read again here.

use std::io;

use serde::Serialize;

const MAX_DIAGNOSTIC_BYTES: usize = 4096;
const CAP_FIELDS: [&str; 5] = ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"];

pub(super) fn verify_status(status: &str, uid: u32, peer_pid: u32) -> io::Result<()> {
    let actual_uid = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .map(|line| line.split_whitespace().collect::<Vec<_>>());
    let expected_uid = uid.to_string();
    if actual_uid
        .as_ref()
        .is_none_or(|values| values.len() != 4 || values.iter().any(|value| *value != expected_uid))
        || !status.lines().any(|line| line == "NoNewPrivs:\t1")
        || ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]
            .iter()
            .any(|field| {
                !status.lines().any(|line| {
                    line.strip_prefix(field)
                        .is_some_and(|value| value == ":\t0000000000000000")
                })
            })
        || !status.lines().any(|line| {
            line.strip_prefix("Groups:")
                .is_some_and(|groups| groups.split_whitespace().next().is_none())
        })
    {
        return Err(io::Error::other(format!(
            "owner must have exact dedicated UID, no groups/capabilities and NoNewPrivileges; status_diagnostic={}",
            diagnostic(status, uid, peer_pid),
        )));
    }
    Ok(())
}

#[derive(Serialize)]
struct FieldDiagnostic {
    occurrences: usize,
    token_count: usize,
    // Only the first four numeric tokens of the first matching line are retained.
    // Malformed, overlong and nonnumeric tokens become null. Admission retains
    // its original first-UID/any-other-line rules, independently of these samples.
    first_values: [Option<u64>; 4],
}

#[derive(Serialize)]
struct StatusDiagnostic {
    version: u8,
    peer_pid: u32,
    expected_uid: u32,
    status_bytes: usize,
    // Bit order: UID, NNP, Inh, Prm, Eff, Bnd, Amb, Groups. 255 means all pass.
    pass_mask: u8,
    // One bit per exact UID token, in real/effective/saved/filesystem order.
    uid_match_mask: u8,
    uid: FieldDiagnostic,
    no_new_privs: FieldDiagnostic,
    // Capability samples are unsigned numeric values parsed in radix 16.
    caps: [FieldDiagnostic; 5],
    groups: FieldDiagnostic,
}

fn sample_field(status: &str, prefix: &str, radix: u32) -> FieldDiagnostic {
    let mut fields = status.lines().filter_map(|line| line.strip_prefix(prefix));
    let first = fields.next();
    let occurrences = usize::from(first.is_some()) + fields.count();
    let mut values = [None; 4];
    let mut token_count = 0;
    if let Some(first) = first {
        for (index, token) in first.split_whitespace().enumerate() {
            token_count += 1;
            if let Some(sample) = values.get_mut(index) {
                let max_digits = if radix == 16 { 16 } else { 20 };
                if token.len() <= max_digits && token.is_ascii() {
                    *sample = u64::from_str_radix(token, radix).ok();
                }
            }
        }
    }
    FieldDiagnostic {
        occurrences,
        token_count,
        first_values: values,
    }
}

fn diagnostic(status: &str, uid: u32, peer_pid: u32) -> String {
    let expected_uid = uid.to_string();
    let mut uid_match_mask = 0_u8;
    let mut uid_token_count = 0;
    if let Some(line) = status.lines().find_map(|line| line.strip_prefix("Uid:")) {
        for (index, value) in line.split_whitespace().enumerate() {
            uid_token_count += 1;
            if index < 4 && value == expected_uid {
                uid_match_mask |= 1 << index;
            }
        }
    }
    let uid_pass = uid_token_count == 4 && uid_match_mask == 15;
    let mut pass_mask = u8::from(uid_pass);
    pass_mask |= u8::from(status.lines().any(|line| line == "NoNewPrivs:\t1")) << 1;
    for (index, field) in CAP_FIELDS.iter().enumerate() {
        let passes = status.lines().any(|line| {
            line.strip_prefix(field)
                .is_some_and(|value| value == ":\t0000000000000000")
        });
        pass_mask |= u8::from(passes) << (index + 2);
    }
    let groups_pass = status.lines().any(|line| {
        line.strip_prefix("Groups:")
            .is_some_and(|groups| groups.split_whitespace().next().is_none())
    });
    pass_mask |= u8::from(groups_pass) << 7;
    let value = StatusDiagnostic {
        version: 1,
        peer_pid,
        expected_uid: uid,
        status_bytes: status.len(),
        pass_mask,
        uid_match_mask,
        uid: sample_field(status, "Uid:", /*radix*/ 10),
        no_new_privs: sample_field(status, "NoNewPrivs:", /*radix*/ 10),
        caps: CAP_FIELDS.map(|field| sample_field(status, &format!("{field}:"), /*radix*/ 16)),
        groups: sample_field(status, "Groups:", /*radix*/ 10),
    };
    // All serialized strings are field names owned by this module. The fixed
    // arrays and integer values bound output independently of input length.
    match serde_json::to_string(&value) {
        Ok(json) if json.len() <= MAX_DIAGNOSTIC_BYTES => json,
        _ => format!(
            "{{\"version\":1,\"peer_pid\":{peer_pid},\"expected_uid\":{uid},\"pass_mask\":{pass_mask},\"uid_match_mask\":{uid_match_mask},\"details_omitted\":true}}"
        ),
    }
}

#[cfg(test)]
#[path = "authority_host_owner_status_tests.rs"]
mod tests;
