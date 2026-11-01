//! Stateful local provider: durable lease, billing counter and operation dedup.

use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::sync::atomic::{AtomicU64, Ordering};

use std::path::Path;

use crate::common::{Job, Result, atomic, checksum, ensure, fault, read, seal, unseal};

pub struct Provider {
    run: String,
    job_checksum: u64,
    generation: u64,
    effects: BTreeMap<String, String>,
    count: u64,
    charged_micros: u64,
    replies: BTreeMap<String, (u64, String)>,
    poisoned: bool,
}

impl Provider {
    fn open(path: &Path, job: &Job) -> Result<Self> {
        if !path.exists() {
            return Ok(Self {
                run: job.run.clone(),
                job_checksum: job.checksum,
                generation: 0,
                effects: BTreeMap::new(),
                count: 0,
                charged_micros: 0,
                replies: BTreeMap::new(),
                poisoned: false,
            });
        }
        let text = read(path)?;
        let mut lines = unseal(&text)?.lines();
        let header: Vec<_> = lines
            .next()
            .ok_or("missing provider header")?
            .split('\t')
            .collect();
        ensure(
            header.len() == 6 && header[0] == "PROVIDER" && header[1] == job.run,
            "wrong provider run",
        )?;
        ensure(
            u64::from_str_radix(header[2], 16)? == job.checksum,
            "wrong provider job",
        )?;
        let mut result = Self {
            run: job.run.clone(),
            job_checksum: job.checksum,
            generation: header[3].parse()?,
            count: header[4].parse()?,
            charged_micros: header[5].parse()?,
            effects: BTreeMap::new(),
            replies: BTreeMap::new(),
            poisoned: false,
        };
        let mut total = 0;
        let mut indexes = Vec::new();
        for line in lines {
            let p: Vec<_> = line.split('\t').collect();
            if p.first() == Some(&"REPLY") {
                ensure(
                    p.len() == 4 && result.replies.len() < 1024,
                    "reply capacity or shape",
                )?;
                let hash = u64::from_str_radix(p[2], 16)?;
                ensure(
                    result
                        .replies
                        .insert(p[1].into(), (hash, unhex(p[3])?))
                        .is_none(),
                    "duplicate reply",
                )?;
                continue;
            }
            ensure(
                p.len() == 7 && p[0] == "EFFECT" && p[1] == job.run,
                "bad effect",
            )?;
            ensure(
                result.effects.insert(p[2].into(), line.into()).is_none(),
                "duplicate effect",
            )?;
            total += p[5].parse::<u64>()?;
            indexes.push(p[6].parse::<u64>()?);
        }
        indexes.sort();
        ensure(
            indexes == (1..=result.count).collect::<Vec<_>>() && total == result.charged_micros,
            "inconsistent billing state",
        )?;
        Ok(result)
    }

    fn persist(&self, path: &Path) -> Result<()> {
        let mut text = format!(
            "PROVIDER\t{}\t{:016x}\t{}\t{}\t{}\n",
            self.run, self.job_checksum, self.generation, self.count, self.charged_micros
        );
        for effect in self.effects.values() {
            text.push_str(effect);
            text.push('\n');
        }
        for (id, (hash, response)) in &self.replies {
            text.push_str(&format!("REPLY\t{id}\t{hash:016x}\t{}\n", hex(response)));
        }
        atomic(path, &seal(&text))
    }

    fn commit(&mut self, path: &Path, inject: bool) -> Result<()> {
        self.poisoned = true;
        if inject {
            return Err(std::io::Error::from_raw_os_error(28).into());
        }
        self.persist(path)?;
        self.poisoned = false;
        Ok(())
    }

    fn request(
        &mut self,
        fields: &[&str],
        job: &Job,
        path: &Path,
        stop: &str,
        marker: &Path,
    ) -> Result<String> {
        ensure(fields.len() >= 2 && fields[1] == self.run, "wrong run")?;
        if fields[0] == "LEASE" {
            ensure(fields.len() == 2, "bad lease")?;
            self.generation = self
                .generation
                .checked_add(1)
                .ok_or("generation overflow")?;
            self.commit(path, false)?;
            return Ok(format!("LEASE\t{}", self.generation));
        }
        ensure(
            fields.len() >= 3 && fields[2].parse::<u64>()? == self.generation,
            "stale owner generation",
        )?;
        if fields[0] == "CHECK" {
            ensure(fields.len() == 3, "bad check")?;
            return Ok("OK".into());
        }
        ensure(fields.len() == 6 && fields[0] == "CALL", "bad call")?;
        let opid = fields[3];
        let expected = job
            .frames
            .iter()
            .find(|f| {
                f.opid == opid && (f.event == "received:READ" || f.event == "received:REFRESH")
            })
            .ok_or("unknown operation")?;
        let action = expected.event.split(':').nth(1).ok_or("no action")?;
        ensure(
            fields[4] == action && fields[5].parse::<u64>()? == expected.provider_micros,
            "operation content mismatch",
        )?;
        if let Some(receipt) = self.effects.get(opid) {
            return Ok(receipt.clone());
        }
        self.count = self.count.checked_add(1).ok_or("counter overflow")?;
        self.charged_micros = self
            .charged_micros
            .checked_add(expected.provider_micros)
            .ok_or("balance overflow")?;
        let receipt = format!(
            "EFFECT\t{}\t{}\t{}\t{}\t{}\t{}",
            self.run, opid, action, expected.token, expected.provider_micros, self.count
        );
        self.effects.insert(opid.into(), receipt.clone());
        self.commit(path, stop == "provider_storage_error")?;
        fault("provider_committed", stop, marker)?;
        Ok(receipt)
    }
}

fn hex(text: &str) -> String {
    text.as_bytes().iter().map(|b| format!("{b:02x}")).collect()
}

fn unhex(text: &str) -> Result<String> {
    ensure(text.len() % 2 == 0 && text.is_ascii(), "invalid hex")?;
    let bytes: std::result::Result<Vec<_>, _> = (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16))
        .collect();
    Ok(String::from_utf8(bytes?)?)
}

pub fn serve(job: &Job, path: &Path, mailbox: &Path, stop: &str, marker: &Path) -> Result<()> {
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path.with_extension("lock"))?;
    lock.try_lock()?;
    let mut provider = Provider::open(path, job)?;
    provider.persist(path)?;
    std::fs::create_dir_all(mailbox)?;
    atomic(&mailbox.join("READY"), &format!("{}\n", std::process::id()))?;
    loop {
        let mut requests: Vec<_> = std::fs::read_dir(mailbox)?
            .filter_map(|entry| entry.ok())
            .map(|entry| entry.path())
            .filter(|path| path.extension().is_some_and(|ext| ext == "req"))
            .collect();
        requests.sort();
        if requests.is_empty() {
            std::thread::sleep(std::time::Duration::from_millis(1));
            continue;
        }
        for request_path in requests {
            let text = read(&request_path)?;
            let p: Vec<_> = unseal(&text)?.trim_end().split('\t').collect();
            ensure(p.len() == 3 && p[0] == "REQ", "request envelope")?;
            ensure(
                p[1].bytes().all(|c| c.is_ascii_digit() || c == b'-'),
                "request id",
            )?;
            let id = p[1];
            let request = unhex(p[2])?;
            let hash = checksum(request.as_bytes());
            let response = if let Some((prior_hash, response)) = provider.replies.get(id) {
                ensure(*prior_hash == hash, "request ID content conflict")?;
                response.clone()
            } else {
                ensure(provider.replies.len() < 1024, "reply capacity")?;
                let fields: Vec<_> = request.split('\t').collect();
                let response = match provider.request(&fields, job, path, stop, marker) {
                    Ok(response) => response,
                    Err(error) => {
                        if provider.poisoned {
                            return Err(error);
                        }
                        format!("ERR\t{error}")
                    }
                };
                provider.replies.insert(id.into(), (hash, response.clone()));
                provider.commit(path, false)?;
                response
            };
            atomic(
                &mailbox.join(format!("{id}.resp")),
                &seal(&format!("RESP\t{id}\t{}\n", hex(&response))),
            )?;
            std::fs::remove_file(request_path)?;
        }
    }
}

static REQUEST: AtomicU64 = AtomicU64::new(0);

pub fn rpc(mailbox: &Path, request: &str) -> Result<String> {
    let id = format!(
        "{}-{:010}",
        std::process::id(),
        REQUEST.fetch_add(1, Ordering::Relaxed)
    );
    let request_path = mailbox.join(format!("{id}.req"));
    let response_path = mailbox.join(format!("{id}.resp"));
    atomic(
        &request_path,
        &seal(&format!("REQ\t{id}\t{}\n", hex(request))),
    )?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while !response_path.exists() {
        ensure(
            std::time::Instant::now() < deadline,
            "provider response timeout",
        )?;
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
    let text = read(&response_path)?;
    let fields: Vec<_> = unseal(&text)?.trim_end().split('\t').collect();
    ensure(
        fields.len() == 3 && fields[0] == "RESP" && fields[1] == id,
        "response envelope",
    )?;
    let response = unhex(fields[2])?;
    std::fs::remove_file(response_path)?;
    ensure(
        !response.starts_with("ERR") && !response.is_empty(),
        &format!("provider rejected: {response}"),
    )?;
    Ok(response)
}
