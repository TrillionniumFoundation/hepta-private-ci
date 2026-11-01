//! Native durable replay owner; numerical state remains an opaque Python receipt.

use std::collections::BTreeMap;
use std::path::Path;

use crate::common::{Job, Result, atomic, checksum, ensure, fault, lock, read, seal, unseal};
use crate::provider::rpc;

struct State {
    run: String,
    job_checksum: u64,
    generation: u64,
    cursor: usize,
    clock_ns: u64,
    fee_micros: u64,
    numeric_state: String,
    receipts: BTreeMap<String, String>,
}

impl State {
    fn open(path: &Path, job: &Job) -> Result<Self> {
        if !path.exists() {
            return Ok(Self {
                run: job.run.clone(),
                job_checksum: job.checksum,
                generation: 0,
                cursor: 0,
                clock_ns: 0,
                fee_micros: 0,
                numeric_state: job.initial.clone(),
                receipts: BTreeMap::new(),
            });
        }
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let header: Vec<_> = lines
            .next()
            .ok_or("missing owner header")?
            .split('\t')
            .collect();
        ensure(
            header.len() == 7 && header[0] == "OWNER" && header[1] == job.run,
            "wrong owner run",
        )?;
        ensure(
            u64::from_str_radix(header[2], 16)? == job.checksum,
            "wrong owner job",
        )?;
        let numeric: Vec<_> = lines
            .next()
            .ok_or("no numeric state")?
            .split('\t')
            .collect();
        ensure(
            numeric.len() == 2 && numeric[0] == "STATE",
            "bad numeric state",
        )?;
        let mut result = Self {
            run: job.run.clone(),
            job_checksum: job.checksum,
            generation: header[3].parse()?,
            cursor: header[4].parse()?,
            clock_ns: header[5].parse()?,
            fee_micros: header[6].parse()?,
            numeric_state: numeric[1].into(),
            receipts: BTreeMap::new(),
        };
        ensure(result.cursor <= job.frames.len(), "owner cursor overflow")?;
        for line in lines {
            let fields: Vec<_> = line.split('\t').collect();
            ensure(
                fields.len() == 7 && fields[0] == "EFFECT" && fields[1] == job.run,
                "bad inbox",
            )?;
            ensure(
                result
                    .receipts
                    .insert(fields[2].into(), line.into())
                    .is_none(),
                "duplicate inbox",
            )?;
        }
        Ok(result)
    }

    fn persist(&self, path: &Path) -> Result<()> {
        let mut text = format!(
            "OWNER\t{}\t{:016x}\t{}\t{}\t{}\t{}\nSTATE\t{}\n",
            self.run,
            self.job_checksum,
            self.generation,
            self.cursor,
            self.clock_ns,
            self.fee_micros,
            self.numeric_state
        );
        for receipt in self.receipts.values() {
            text.push_str(receipt);
            text.push('\n');
        }
        atomic(path, &seal(&text))
    }
}

pub fn run(job: &Job, path: &Path, socket: &Path, stop: &str, marker: &Path) -> Result<()> {
    let lock_path = path.with_extension("lock");
    let lease_lock = lock(&lock_path)?;
    let mut state = State::open(path, job)?;
    let lease = rpc(socket, &format!("LEASE\t{}", job.run))?;
    let fields: Vec<_> = lease.split('\t').collect();
    ensure(
        fields.len() == 2 && fields[0] == "LEASE",
        "bad lease receipt",
    )?;
    state.generation = fields[1].parse()?;
    state.persist(path)?;
    drop(lease_lock);
    fault("owner_leased", stop, marker)?;
    while state.cursor < job.frames.len() {
        let commit_lock = lock(&lock_path)?;
        let observed = State::open(path, job)?;
        ensure(
            observed.generation == state.generation && observed.cursor == state.cursor,
            "stale owner state generation or cursor",
        )?;
        rpc(socket, &format!("CHECK\t{}\t{}", job.run, state.generation))?;
        let frame = &job.frames[state.cursor];
        ensure(
            frame.sequence == state.cursor
                && checksum(state.numeric_state.as_bytes()) == frame.before_checksum,
            "state transition identity mismatch",
        )?;
        if frame.event == "received:READ" || frame.event == "received:REFRESH" {
            let action = frame.event.split(':').nth(1).ok_or("no action")?;
            let receipt = rpc(
                socket,
                &format!(
                    "CALL\t{}\t{}\t{}\t{}\t{}",
                    job.run, state.generation, frame.opid, action, frame.provider_micros
                ),
            )?;
            let p: Vec<_> = receipt.split('\t').collect();
            ensure(
                p.len() == 7
                    && p[0] == "EFFECT"
                    && p[1] == job.run
                    && p[2] == frame.opid
                    && p[3] == action
                    && p[4].parse::<i32>()? == frame.token
                    && p[5].parse::<u64>()? == frame.provider_micros,
                "bad provider response",
            )?;
            ensure(
                !state.receipts.contains_key(&frame.opid),
                "inbox response replay",
            )?;
            fault("owner_received_before_commit", stop, marker)?;
            state.receipts.insert(frame.opid.clone(), receipt);
        }
        state.clock_ns = state
            .clock_ns
            .checked_add(frame.elapsed_ns)
            .ok_or("clock overflow")?;
        state.fee_micros = state
            .fee_micros
            .checked_add(frame.charged_micros)
            .ok_or("fee overflow")?;
        state.numeric_state = frame.after_state.clone();
        state.cursor += 1;
        state.persist(path)?;
        drop(commit_lock);
        let stage = if frame.event.starts_with("prepared:") {
            "owner_prepared"
        } else if frame.event.starts_with("elapsed:") {
            "owner_elapsed"
        } else if frame.event == "received:READ" || frame.event == "received:REFRESH" {
            "owner_received"
        } else if frame.event.starts_with("applied:") {
            "owner_applied"
        } else if frame.event == "query_boundary" {
            "owner_boundary"
        } else {
            "none"
        };
        fault(stage, stop, marker)?;
    }
    println!(
        "COMPLETE\t{}\t{}\t{}\t{}\t{}",
        state.run, state.generation, state.cursor, state.clock_ns, state.fee_micros
    );
    Ok(())
}
