use std::env;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_control_plane::CanonicalDecisionEnvelopeV1;
use codex_hepta_control_plane::PlannerStoreError;
use codex_hepta_control_plane::PlannerStoreFailpointV1;
use codex_hepta_control_plane::PlannerStoreRecordKindV1;
use codex_hepta_control_plane::PlannerStoreV1;
use codex_hepta_types::Digest32;

const QUALIFICATION_RECORDS: u64 = 256;
const MINIMUM_APPEND_OPS_PER_SECOND: u64 = 25;

fn envelope(sequence: u64) -> CanonicalDecisionEnvelopeV1 {
    CanonicalDecisionEnvelopeV1 {
        operation_identity_digest: Digest32::of_bytes(
            format!("named-host-operation:{sequence}").as_bytes(),
        ),
        snapshot_bytes: format!("snapshot:{sequence}").into_bytes(),
        prepared_plan_bytes: format!("prepared:{sequence}").into_bytes(),
        ndu_evaluation_bytes: format!("ndu:{sequence}").into_bytes(),
        plan_receipt_bytes: format!("plan-receipt:{sequence}").into_bytes(),
        grant_request_set_bytes: format!("grant-requests:{sequence}").into_bytes(),
    }
}

fn required_env(name: &'static str) -> Result<String, String> {
    let value = env::var(name).map_err(|_| format!("missing {name}"))?;
    if value.trim().is_empty() || value.as_bytes().contains(&0) {
        return Err(format!("invalid {name}"));
    }
    Ok(value)
}

fn json_string(value: &str) -> String {
    let mut result = String::with_capacity(value.len() + 2);
    result.push('"');
    for character in value.chars() {
        match character {
            '"' => result.push_str("\\\""),
            '\\' => result.push_str("\\\\"),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            value if value.is_control() => {
                use std::fmt::Write as _;
                write!(&mut result, "\\u{:04x}", u32::from(value)).expect("write JSON escape");
            }
            value => result.push(value),
        }
    }
    result.push('"');
    result
}

fn unique_directory() -> Result<PathBuf, String> {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    let path = env::temp_dir().join(format!(
        "hepta-control-runtime-qualification-{}-{nonce}",
        std::process::id()
    ));
    fs::create_dir_all(&path).map_err(|error| error.to_string())?;
    Ok(path)
}

fn clean_directory(path: &Path) {
    let _ = fs::remove_dir_all(path);
}

fn run() -> Result<(), String> {
    let receipt_path = PathBuf::from(required_env("HEPTA_CONTROL_RUNTIME_RECEIPT_PATH")?);
    let source_sha = required_env("HEPTA_CONTROL_RUNTIME_SOURCE_SHA")?;
    let source_tree = required_env("HEPTA_CONTROL_RUNTIME_SOURCE_TREE")?;
    let host_id = required_env("HEPTA_CONTROL_RUNTIME_HOST_ID")?;
    let lane = required_env("HEPTA_CONTROL_RUNTIME_LANE")?;
    let rustc = required_env("HEPTA_CONTROL_RUNTIME_RUSTC")?;
    let filesystem = required_env("HEPTA_CONTROL_RUNTIME_FS_PROFILE")?;
    let directory = unique_directory()?;
    let store_path = directory.join("planner.store");
    let backup_path = directory.join("planner.backup");
    let restored_path = directory.join("planner.restored");

    let qualification = (|| -> Result<(u128, u64, bool, bool, bool, bool), String> {
        let elapsed_nanos;
        let append_ops_per_second;
        let expected_complete_records;
        {
            let mut store = PlannerStoreV1::open(&store_path).map_err(|error| error.to_string())?;
            let started = Instant::now();
            for sequence in 0..QUALIFICATION_RECORDS {
                store
                    .append_decision(&envelope(sequence))
                    .map_err(|error| error.to_string())?;
            }
            elapsed_nanos = started.elapsed().as_nanos().max(1);
            append_ops_per_second = u64::try_from(
                u128::from(QUALIFICATION_RECORDS)
                    .saturating_mul(1_000_000_000)
                    .checked_div(elapsed_nanos)
                    .unwrap_or(0),
            )
            .unwrap_or(u64::MAX);

            let oversized = vec![0_u8; 5 * 1024 * 1024];
            let overload_rejected = matches!(
                store.append(PlannerStoreRecordKindV1::Dispatch, &oversized),
                Err(PlannerStoreError::PayloadTooLarge)
            );
            if !overload_rejected {
                return Err("oversized planner-store payload was not rejected".to_string());
            }

            store.set_failpoint(Some(PlannerStoreFailpointV1::AfterFramePrefix));
            let partial_write_rejected = matches!(
                store.append_decision(&envelope(QUALIFICATION_RECORDS + 1)),
                Err(PlannerStoreError::InjectedFailure(
                    PlannerStoreFailpointV1::AfterFramePrefix
                ))
            );
            if !partial_write_rejected {
                return Err("partial-write failpoint did not close the append".to_string());
            }
            expected_complete_records = store.records().len();
        }

        let recovered_count;
        {
            let mut recovered =
                PlannerStoreV1::open(&store_path).map_err(|error| error.to_string())?;
            recovered_count = recovered.records().len();
            if recovered_count != expected_complete_records {
                return Err("partial-tail recovery changed the complete record frontier".to_string());
            }
            recovered
                .append_checkpoint(b"named-host-external-anchor")
                .map_err(|error| error.to_string())?;
            recovered
                .backup(&backup_path)
                .map_err(|error| error.to_string())?;
        }

        PlannerStoreV1::restore_from_backup(&restored_path, &backup_path)
            .map_err(|error| error.to_string())?;
        let restored =
            PlannerStoreV1::open(&restored_path).map_err(|error| error.to_string())?;
        let backup_rollback_ok = restored.records().len() == recovered_count + 1;
        let restart_recovery_ok = recovered_count == expected_complete_records;
        let performance_slo_met = append_ops_per_second >= MINIMUM_APPEND_OPS_PER_SECOND;
        let complete = backup_rollback_ok && restart_recovery_ok && performance_slo_met;
        Ok((
            elapsed_nanos,
            append_ops_per_second,
            restart_recovery_ok,
            backup_rollback_ok,
            performance_slo_met,
            complete,
        ))
    })();

    clean_directory(&directory);
    let (
        elapsed_nanos,
        append_ops_per_second,
        restart_recovery_ok,
        backup_rollback_ok,
        performance_slo_met,
        complete,
    ) = qualification?;
    if !complete {
        return Err("named-host qualification did not satisfy its bounded SLO".to_string());
    }

    let receipt = format!(
        concat!(
            "{{\n",
            "  \"schema\": \"hepta.control-runtime.named-host.v1\",\n",
            "  \"source_sha\": {},\n",
            "  \"source_tree\": {},\n",
            "  \"lane\": {},\n",
            "  \"host_id\": {},\n",
            "  \"host_os\": {},\n",
            "  \"host_arch\": {},\n",
            "  \"rustc\": {},\n",
            "  \"filesystem_profile\": {},\n",
            "  \"decision_records\": {},\n",
            "  \"append_elapsed_nanos\": {},\n",
            "  \"append_ops_per_second\": {},\n",
            "  \"minimum_append_ops_per_second\": {},\n",
            "  \"restart_recovery_ok\": {},\n",
            "  \"partial_write_recovery_ok\": {},\n",
            "  \"overload_rejection_ok\": {},\n",
            "  \"backup_rollback_ok\": {},\n",
            "  \"performance_slo_met\": {},\n",
            "  \"activation\": false,\n",
            "  \"release\": false,\n",
            "  \"complete\": {}\n",
            "}}\n"
        ),
        json_string(&source_sha),
        json_string(&source_tree),
        json_string(&lane),
        json_string(&host_id),
        json_string(env::consts::OS),
        json_string(env::consts::ARCH),
        json_string(&rustc),
        json_string(&filesystem),
        QUALIFICATION_RECORDS,
        elapsed_nanos,
        append_ops_per_second,
        MINIMUM_APPEND_OPS_PER_SECOND,
        restart_recovery_ok,
        restart_recovery_ok,
        true,
        backup_rollback_ok,
        performance_slo_met,
        complete,
    );
    if let Some(parent) = receipt_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(&receipt_path, receipt.as_bytes()).map_err(|error| error.to_string())?;
    print!("{receipt}");
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("control.runtime named-host qualification failed: {error}");
        std::process::exit(1);
    }
}
