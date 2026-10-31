//! A state-adoption coordinator; NeuronRuntime remains the sparse-state owner.
use crate::contract::Action;
use crate::contract::Phase;
use crate::contract::Request;
use crate::contract::ZERO;
use crate::contract::hash;
use crate::native;
use crate::settlement::Body;
use crate::settlement::Dispatch;
use crate::settlement::Observation;
use crate::settlement::Record;
use crate::settlement::Terminal;
use crate::settlement::history;
use crate::store::Fault;
use crate::store::Store;
use serde_json::Value;
use serde_json::json;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

fn read_source(
    root: &Path,
    relative: &str,
    query: &str,
    attempts: &mut u64,
) -> Result<Observation, String> {
    let mut path = root.to_path_buf();
    for component in Path::new(relative).components() {
        path.push(component.as_os_str());
        if fs::symlink_metadata(&path)
            .map_err(|e| e.to_string())?
            .file_type()
            .is_symlink()
        {
            return Err("linked source path refused".into());
        }
    }
    if !path
        .canonicalize()
        .map_err(|e| e.to_string())?
        .starts_with(root)
    {
        return Err("source scope changed".into());
    }
    if !fs::symlink_metadata(&path)
        .map_err(|e| e.to_string())?
        .is_file()
    {
        return Err("nonregular source refused".into());
    }
    *attempts = 1;
    let source = OpenOptions::new()
        .read(true)
        .custom_flags(crate::store::OPEN_FLAGS)
        .open(path)
        .map_err(|e| e.to_string())?;
    let metadata = source.metadata().map_err(|e| e.to_string())?;
    if !metadata.is_file() || metadata.len() > 65_536 {
        return Err("bounded regular source required".into());
    }
    let mut bytes = Vec::new();
    source
        .take(65_537)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 65_536 {
        return Err("bounded source size exceeded".into());
    }
    let text = std::str::from_utf8(&bytes).map_err(|e| e.to_string())?;
    let answer = text.lines().find_map(|line| {
        line.split_once('=')
            .filter(|(key, _)| *key == query)
            .map(|(_, v)| v.to_owned())
    });
    Ok(Observation::Read {
        source_digest: codex_hepta_types::Digest32::of_bytes(&bytes).to_string(),
        bytes: bytes.len(),
        answer,
    })
}

pub fn execute(
    store: Store,
    data: &Path,
    request: Request,
    fault: &Fault,
) -> Result<Value, String> {
    fault.at("locked")?;
    let data = data.canonicalize().map_err(|e| e.to_string())?;
    if !data.is_dir() {
        return Err("task root is not a directory".into());
    }
    let data_string = data.to_str().ok_or("non-UTF8 task root")?.to_owned();
    let rows = history(&store)?;
    let previous = rows.last();
    if previous.is_some_and(|r| r.body.data_root != data_string) {
        return Err("immutable task source scope changed".into());
    }
    let owner_anchor = previous.map_or(ZERO, |r| r.body.native.after.as_str());
    let sequence = rows.len() as u64;
    // A historical replay must not trigger native suffix recovery past an unknown effect.
    if store
        .read::<Dispatch>(&format!("dispatch-{:04}.json", sequence + 1))?
        .is_some()
    {
        return Err("Indeterminate: dispatched without an atomic observation/credit record; execution forbidden".into());
    }
    if request.sequence <= sequence {
        let row = rows
            .get(request.sequence.saturating_sub(1) as usize)
            .ok_or("invalid replay sequence")?;
        if row.body.request != request {
            return Err("replay payload conflict".into());
        }
        // Replay verifies the current native frontier without running the model.
        let _owner = native::Owner::open(&store.root, &request, owner_anchor, sequence)?;
        return Ok(
            json!({"status":"settled", "replayed":true, "new_attempts":0, "record":row, "authority":"DENY_ALL", "production_activation":false}),
        );
    }
    if request.sequence != sequence + 1
        || request.predecessor != previous.map_or(ZERO, |r| r.digest.as_str())
    {
        return Err("stale or future settlement predecessor".into());
    }
    request.validate(previous.map(|r| &r.body.request))?;
    if previous.is_some_and(|r| r.body.terminal.is_some()) {
        return Err("terminal task cannot execute again".into());
    }
    if matches!(request.action, Action::Read { .. })
        && !matches!(request.checkpoint.phase, Phase::Active)
        && request.checkpoint.time_us < request.config.deadline_us
        && request
            .checkpoint
            .cancellation
            .at_us
            .is_none_or(|t| request.checkpoint.time_us < t)
    {
        return Err("read refused during refractory holding".into());
    }
    let price = previous.map_or(request.config.credit.initial_micros, |r| {
        r.body.price_after_micros
    });
    let residue = previous.map_or(0, |r| r.body.price_after_residue);
    if request.expected_price_micros != price || request.expected_price_residue != residue {
        return Err("stale resource price".into());
    }
    let elapsed_us =
        request.checkpoint.time_us - previous.map_or(0, |r| r.body.request.checkpoint.time_us);
    let (admission_price, admission_residue) =
        request.config.credit.next(price, residue, 0, elapsed_us);
    let request_digest = hash(&request)?;
    let prepared_name = format!("prepared-{:04}.json", request.sequence);
    if let Some(prepared) = store.read::<Request>(&prepared_name)?
        && prepared != request
    {
        return Err("prepared payload conflict".into());
    }
    let dispatch_name = format!("dispatch-{:04}.json", request.sequence);
    store.publish(&prepared_name, &request, fault)?;
    fault.at("prepared")?;
    store.publish(
        &dispatch_name,
        &Dispatch {
            request_digest: request_digest.clone(),
        },
        fault,
    )?;
    fault.at("dispatched")?;
    // Native bootstrap itself writes a journal header; put even that behind the fence.
    let mut owner = native::Owner::open(&store.root, &request, owner_anchor, sequence)?;
    store.sync()?;
    let native = owner.tick(&request, owner_anchor)?;
    fault.at("native_committed")?;
    let spent = previous.map_or(0, |r| r.body.total_spent);
    let mut attempts = 0;
    let mut observation = Observation::None;
    let mut terminal = None;
    if request
        .checkpoint
        .cancellation
        .at_us
        .is_some_and(|t| request.checkpoint.time_us >= t)
    {
        terminal = Some(Terminal::Cancelled);
    } else if request.checkpoint.time_us >= request.config.deadline_us {
        terminal = Some(Terminal::Deadline);
    } else {
        match &request.action {
            Action::Stop => terminal = Some(Terminal::Stopped),
            Action::Wait => {}
            Action::Read {
                relative_path,
                query,
            } => {
                if spent >= request.config.read_budget {
                    terminal = Some(Terminal::BudgetExhausted);
                } else if !request
                    .config
                    .credit
                    .permits(admission_price, admission_residue)
                {
                    terminal = Some(Terminal::PriceLimited);
                } else if native.abstain {
                    terminal = Some(Terminal::NativeAbstained);
                } else {
                    fault.at("effect_entered")?;
                    match read_source(&data, relative_path, query, &mut attempts) {
                        Ok(value) => observation = value,
                        Err(error) => {
                            observation = Observation::Failed { error };
                            terminal = Some(Terminal::ReadFailed);
                        }
                    }
                }
            }
        }
    }
    fault.at("effect_completed")?;
    let (next_price, next_residue) = request
        .config
        .credit
        .next(price, residue, attempts, elapsed_us);
    let body = Body {
        request,
        request_digest,
        data_root: data_string,
        native,
        attempts,
        total_spent: spent + attempts,
        price_before_micros: price,
        price_after_micros: next_price,
        price_before_residue: residue,
        price_after_residue: next_residue,
        admission_price_micros: admission_price,
        admission_price_residue: admission_residue,
        terminal,
        observation,
    };
    crate::settlement::validate_outcome(&body, spent)?;
    let record = Record {
        digest: hash(&body)?,
        body,
    };
    store.publish(
        &format!("settled-{:04}.json", record.body.request.sequence),
        &record,
        fault,
    )?;
    fault.at("published")?;
    Ok(
        json!({"status":"settled", "replayed":false, "new_attempts":attempts, "record":record, "authority":"DENY_ALL", "production_activation":false}),
    )
}
