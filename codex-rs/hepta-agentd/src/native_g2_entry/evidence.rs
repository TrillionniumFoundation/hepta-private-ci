//! Read-only evidence from this boot's actual process and original Root DTOs.

use super::boot::Boot;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    schema_version: u32,
    pub(super) scenario: String,
    nonce: String,
}

pub(super) struct Evidence {
    plan: Plan,
    sequence: u64,
}

impl Evidence {
    pub(super) fn read() -> io::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open("/test/hepta-g2-run.json")?;
        let stat = file.metadata()?;
        if !stat.is_file()
            || stat.uid() != 0
            || stat.nlink() != 1
            || stat.mode() & 0o7777 != 0o400
            || stat.len() > 1024
        {
            return Err(io::Error::other(
                "bounded original Root0400 acceptance plan required",
            ));
        }
        let mut bytes = Vec::new();
        file.take(1025).read_to_end(&mut bytes)?;
        let plan: Plan = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if plan.schema_version != 1
            || !matches!(
                plan.scenario.as_str(),
                "steady-state-v1" | "manager-exit-after-terminal-v1"
            )
            || plan.nonce.len() != 64
            || !plan
                .nonce
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err(io::Error::other("unknown original finite acceptance plan"));
        }
        Ok(Self { plan, sequence: 0 })
    }

    pub(super) fn scenario(&self) -> &str {
        &self.plan.scenario
    }

    pub(super) fn emit(&mut self, event: &str, payload: impl Serialize) -> io::Result<()> {
        use std::io::Write;
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("event overflow"))?;
        let record = serde_json::json!({"schema_version":1,"scenario":self.plan.scenario,
            "nonce":self.plan.nonce,"event":event,"sequence":sequence,"payload":payload});
        let bytes = serde_json::to_vec(&record).map_err(io::Error::other)?;
        if bytes.len() > 65536 {
            return Err(io::Error::other("original evidence bound exceeded"));
        }
        let mut output = std::io::stdout().lock();
        output.write_all(b"HEPTA_G2_EVIDENCE_V1 ")?;
        output.write_all(&bytes)?;
        output.write_all(b"\n")?;
        output.flush()?;
        self.sequence = sequence;
        Ok(())
    }
}

pub(super) fn roles(boot: &Boot) -> io::Result<Value> {
    Ok(
        serde_json::json!({"bootstrap_version":3,"bootstrap_bytes":200,
        "native_boot_id":&boot.page[96..112],"manager_space":&boot.page[112..128],
        "recovery_space":&boot.page[128..144],
        "linux_boot_id":bounded_text("/proc/sys/kernel/random/boot_id",64)?.trim(),
        "processes":{"root":process(1,4)?,"manager":process(boot.pids[0],1)?,
            "workload":process(boot.pids[1],2)?,"recovery":process(boot.pids[2],3)?}}),
    )
}

pub(super) fn process(pid: u32, role: u8) -> io::Result<Value> {
    let stat = bounded_text(&format!("/proc/{pid}/stat"), 4096)?;
    let tail: Vec<_> = stat
        .rsplit_once(") ")
        .ok_or_else(|| io::Error::other("stat name absent"))?
        .1
        .split_whitespace()
        .collect();
    let number = |at: usize| -> io::Result<u64> {
        tail.get(at)
            .ok_or_else(|| io::Error::other("stat field absent"))?
            .parse()
            .map_err(io::Error::other)
    };
    let status = bounded_text(&format!("/proc/{pid}/status"), 16384)?;
    let values = |name: &str, radix| -> io::Result<Vec<u64>> {
        let line = status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .ok_or_else(|| io::Error::other("actual process status field absent"))?;
        line.split_whitespace()
            .map(|field| u64::from_str_radix(field, radix).map_err(io::Error::other))
            .collect()
    };
    let one = |name, radix| -> io::Result<u64> {
        let values = values(name, radix)?;
        if values.len() != 1 {
            return Err(io::Error::other("single process status value required"));
        }
        Ok(values[0])
    };
    Ok(
        serde_json::json!({"role":role,"pid":pid,"ppid":number(1)?,"sid":number(3)?,
        "start_ticks":number(19)?,"uids":values("Uid:",10)?,"gids":values("Gid:",10)?,
        "groups":values("Groups:",10)?,"nnp":one("NoNewPrivs:",10)?,
        "caps":{"inheritable":one("CapInh:",16)?,"permitted":one("CapPrm:",16)?,
            "effective":one("CapEff:",16)?,"bounding":one("CapBnd:",16)?,"ambient":one("CapAmb:",16)?}}),
    )
}

pub(super) fn bounded_text(path: &str, limit: u64) -> io::Result<String> {
    let mut text = String::new();
    OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?
        .take(limit + 1)
        .read_to_string(&mut text)?;
    if text.len() as u64 > limit {
        return Err(io::Error::other("actual proc observation exceeds bound"));
    }
    Ok(text)
}
