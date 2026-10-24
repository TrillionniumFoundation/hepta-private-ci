//! Actual observation transcript for the finite native acceptance plan.
//! The plan carries no owner registration, authority, signing material or cut.
use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::ProductionDispatchReceipt;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Plan {
    schema_version: u32,
    scenario: String,
    nonce: String,
}

pub(super) struct SourceTerminal {
    pub(super) operation: String,
    pub(super) key: String,
    pub(super) request: Hos2InstallBudgetV1,
    pub(super) state: codex_hepta_memory::LocalOutcomeState,
    pub(super) local_event_id: String,
    pub(super) terminal_json: String,
    pub(super) current: CognitiveCheckpointReceipt,
    pub(super) material_sha256: String,
    pub(super) frontiers: [codex_hepta_contracts::FinalUseFrontier; 2],
}
pub(super) struct Evidence {
    plan: Plan,
    sequence: u64,
    final_token: Option<codex_hepta_memory::CognitiveCheckpointToken>,
    final_owner_pid: u32,
    operation_count: u64,
}
impl Evidence {
    pub(super) fn load() -> io::Result<Self> {
        let file = std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open("/test/hepta-g2-run.json")?;
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.mode() & 0o7777 != 0o400
            || metadata.nlink() != 1
            || metadata.len() > 4096
        {
            return Err(invalid("root-owned finite acceptance plan required"));
        }
        let plan: Plan = serde_json::from_reader(file).map_err(error)?;
        if plan.schema_version != 1
            || ![
                "steady-state-v1",
                "manager-exit-after-terminal-v1",
                "lost-copyout-live-v1",
                "manager-exit-before-terminal-v1",
            ]
            .contains(&plan.scenario.as_str())
            || plan.nonce.len() != 64
            || !plan
                .nonce
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(invalid("invalid finite native acceptance plan"));
        }
        Ok(Self {
            plan,
            sequence: 0,
            final_token: None,
            final_owner_pid: 0,
            operation_count: 0,
        })
    }
    pub(super) fn scenario(&self) -> &str {
        &self.plan.scenario
    }
    pub(super) fn emit(&mut self, event: &str, payload: impl Serialize) -> io::Result<()> {
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| invalid("evidence counter overflow"))?;
        let value = serde_json::json!({"schema_version":1,"scenario":self.plan.scenario,"nonce":self.plan.nonce,
            "event":event,"sequence":self.sequence,"payload":payload});
        let mut bytes = b"HEPTA_G2_EVIDENCE_V1 ".to_vec();
        serde_json::to_writer(&mut bytes, &value).map_err(error)?;
        bytes.push(b'\n');
        if bytes.len() > 128 * 1024 {
            return Err(invalid("bounded native evidence exceeded"));
        }
        let mut stdout = std::io::stdout().lock();
        stdout.write_all(&bytes)?;
        stdout.flush()
    }
    pub(super) fn begin(
        &mut self,
        boot: &NativeBootstrap,
        active: &mut root::Active,
    ) -> io::Result<()> {
        let end = Instant::now() + Duration::from_secs(10);
        let report = loop {
            if let Ok(bytes) = std::fs::read(Path::new(RUNTIME).join("workload-report.json"))
                && bytes.len() <= 16 * 1024
                && let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes)
            {
                break value;
            }
            if Instant::now() >= end {
                return Err(invalid("workload boundary observations absent"));
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        self.emit("roles",serde_json::json!({"bootstrap_version":3,"bootstrap_bytes":200,"native_boot_id":boot.id(96),
            "manager_space":boot.id(112),"recovery_space":boot.id(128),"linux_boot_id":peer(1,0)?.boot_id,
            "processes":{"root":process(1,4)?,"manager":process(2,1)?,"workload":process(3,2)?,"recovery":process(4,3)?}}))?;
        let current = active.service.native_cpu_current()?;
        let initial_material = material(active, &current)?;
        let source = active.rpc.call(commands::Command::Inspect)?;
        let store_device = source["store_device"]
            .as_u64()
            .ok_or_else(|| invalid("actual writer database device absent"))?;
        let store_inode = source["store_inode"]
            .as_u64()
            .ok_or_else(|| invalid("actual writer database inode absent"))?;
        let retained = std::fs::metadata(&initial_material.0)?;
        let mounts = std::fs::read_to_string("/proc/mounts")?;
        if !mounts.lines().any(|line| {
            let fields = line.split_whitespace().collect::<Vec<_>>();
            fields.len() >= 3
                && fields[0] == "/dev/vda"
                && fields[1] == "/state"
                && fields[2] == "ext2"
        }) {
            return Err(invalid("actual retained ext2 mount missing"));
        }
        self.emit("state",serde_json::json!({"source":"/dev/vda","target":"/state","filesystem":"ext2",
            "mount_device":std::fs::metadata("/state")?.dev(),"store_device":store_device,"store_inode":store_inode,
            "root_material_device":retained.dev(),"root_material_inode":retained.ino()}))?;
        let mut boundary = report
            .as_object()
            .cloned()
            .ok_or_else(|| invalid("workload report shape"))?;
        boundary.insert(
            "root_manage_status".into(),
            serde_json::json!(root_denial(boot, 3)?),
        );
        boundary.insert(
            "root_history_status".into(),
            serde_json::json!(root_denial(boot, 4)?),
        );
        self.emit("boundary", boundary)?;
        self.owner_ready("manager", active)
    }

    pub(super) fn owner_ready(&mut self, role: &str, active: &mut root::Active) -> io::Result<()> {
        let current = active.service.native_cpu_current()?;
        let retained = material(active, &current)?;
        let mut ready = active
            .rpc
            .call(commands::Command::Inspect)?
            .as_object()
            .cloned()
            .ok_or_else(|| invalid("original owner inspection shape"))?;
        ready.remove("usage");
        ready.remove("store_device");
        ready.remove("store_inode");
        ready.remove("startup_retained");
        ready.remove("copyout");
        ready.insert("role".into(), serde_json::json!(role));
        ready.insert(
            "current".into(),
            serde_json::to_value(&current).map_err(error)?,
        );
        ready.insert("material_sha256".into(), serde_json::json!(retained.1));
        self.emit("owner_ready", ready)
    }
    pub(super) fn steady_state(&mut self, active: &mut root::Active) -> io::Result<()> {
        for (operation, cap_ns) in [("lower", 25_000_000), ("pause", 0), ("resume", 50_000_000)] {
            let terminal = self.operation(operation, cap_ns, active)?;
            self.acknowledge(&terminal, active)?;
            self.window(operation, active)?;
        }
        Ok(())
    }
    pub(super) fn operation(
        &mut self,
        operation: &str,
        cap_ns: u64,
        active: &mut root::Active,
    ) -> io::Result<SourceTerminal> {
        let prepared = active.rpc.call(commands::Command::Prepare {
            operation: operation.into(),
            cap_ns,
        })?;
        let key = prepared["occurrence_key"]
            .as_str()
            .ok_or_else(|| invalid("original K missing"))?
            .to_owned();
        let request = Hos2InstallBudgetV1::from_json(
            prepared["request_json"]
                .as_str()
                .ok_or_else(|| invalid("original payload missing"))?,
        )
        .map_err(error)?;
        self.emit("prepared", prepared)?;
        let actual = active.rpc.call(commands::Command::Dispatch {
            occurrence_key: key.clone(),
        })?;
        let receipt: ProductionDispatchReceipt =
            serde_json::from_value(actual["receipt"].clone()).map_err(error)?;
        let terminal = receipt
            .target_receipt
            .as_ref()
            .or(receipt.target_reason.as_ref())
            .ok_or_else(|| invalid("original source has no terminal receipt"))?
            .clone();
        self.emit("native_result",serde_json::json!({"operation":operation,"pid":active.registration.peer_pid,"terminal_json":terminal,
            "before":actual["before"],"after":actual["after"]}))?;
        let source = self.source_terminal(
            operation,
            key,
            request,
            receipt.state,
            receipt.local_event_id,
            terminal,
            active,
        )?;
        self.operation_count = self
            .operation_count
            .checked_add(1)
            .ok_or_else(|| invalid("operation counter overflow"))?;
        Ok(source)
    }
    fn source_terminal(
        &mut self,
        operation: &str,
        key: String,
        request: Hos2InstallBudgetV1,
        state: codex_hepta_memory::LocalOutcomeState,
        local_event_id: String,
        terminal_json: String,
        active: &mut root::Active,
    ) -> io::Result<SourceTerminal> {
        let current = active.service.native_cpu_current()?;
        let retained = material(active, &current)?;
        let owner = active.rpc.call(commands::Command::Inspect)?;
        let frontiers: [codex_hepta_contracts::FinalUseFrontier; 2] = [
            serde_json::from_value(owner["device_frontier"].clone()).map_err(error)?,
            serde_json::from_value(owner["notes_frontier"].clone()).map_err(error)?,
        ];
        self.emit("source_terminal",serde_json::json!({"operation":operation,"pid":active.registration.peer_pid,"occurrence_key":key,
            "state":state,"terminal_json":terminal_json,"local_event_id":local_event_id,"current":current,
            "material_sha256":retained.1,"device_frontier":frontiers[0],"notes_frontier":frontiers[1]}))?;
        self.final_token = Some(current.token.clone());
        self.final_owner_pid = active.registration.peer_pid;
        Ok(SourceTerminal {
            operation: operation.into(),
            key,
            request,
            state,
            local_event_id,
            terminal_json,
            current,
            material_sha256: retained.1,
            frontiers,
        })
    }
    pub(super) fn recovered_terminal(
        &mut self,
        old: &SourceTerminal,
        active: &mut root::Active,
    ) -> io::Result<SourceTerminal> {
        let actual = active.rpc.call(commands::Command::ReconcileRetained {
            occurrence_key: old.key.clone(),
        })?;
        let request = Hos2InstallBudgetV1::from_json(
            actual["request_json"]
                .as_str()
                .ok_or_else(|| invalid("retained request absent"))?,
        )
        .map_err(error)?;
        let receipt: codex_hepta_memory::ProductionOutcomeReceipt =
            serde_json::from_value(actual["receipt"].clone()).map_err(error)?;
        let terminal = actual["terminal_json"]
            .as_str()
            .ok_or_else(|| invalid("retained terminal absent"))?
            .to_owned();
        if request != old.request
            || receipt.occurrence_key != old.key
            || receipt.event_id != old.local_event_id
            || receipt.state != old.state
            || terminal != old.terminal_json
            || receipt.external_effect
        {
            return Err(invalid(
                "successor changed the original durable K/D terminal",
            ));
        }
        self.emit("reconciled",serde_json::json!({"operation":old.operation,"pid":active.registration.peer_pid,
            "occurrence_key":receipt.occurrence_key,"request_json":actual["request_json"],"terminal_json":terminal,"usage":actual["usage"]}))?;
        let recovered = self.source_terminal(
            &old.operation,
            old.key.clone(),
            request,
            receipt.state,
            receipt.event_id,
            terminal,
            active,
        )?;
        if recovered.frontiers != old.frontiers {
            return Err(invalid("query of original D changed FinalUse frontiers"));
        }
        Ok(recovered)
    }
    pub(super) fn reconciled_copyout_terminal(
        &mut self,
        operation: &str,
        key: String,
        request: Hos2InstallBudgetV1,
        receipt: codex_hepta_memory::ProductionOutcomeReceipt,
        terminal_json: String,
        active: &mut root::Active,
    ) -> io::Result<SourceTerminal> {
        if receipt.occurrence_key != key || receipt.external_effect {
            return Err(invalid("original observed copyout receipt differs from K"));
        }
        let source = self.source_terminal(
            operation,
            key,
            request,
            receipt.state,
            receipt.event_id,
            terminal_json,
            active,
        )?;
        self.operation_count = self
            .operation_count
            .checked_add(1)
            .ok_or_else(|| invalid("operation counter overflow"))?;
        Ok(source)
    }
    pub(super) fn acknowledge(
        &mut self,
        terminal: &SourceTerminal,
        active: &mut root::Active,
    ) -> io::Result<()> {
        let mut ack = active
            .rpc
            .call(commands::Command::Retire {
                through: terminal.request.delivery.clone(),
            })?
            .as_object()
            .cloned()
            .ok_or_else(|| invalid("native retirement observation shape"))?;
        let after = active.service.native_cpu_current()?;
        if after.token != terminal.current.token {
            return Err(invalid(
                "native retirement changed the acknowledged original terminal cut",
            ));
        }
        ack.insert("operation".into(), serde_json::json!(terminal.operation));
        ack.insert(
            "current_token".into(),
            serde_json::to_value(&terminal.current.token).map_err(error)?,
        );
        self.emit("history_ack", ack)
    }
    pub(super) fn window(&mut self, operation: &str, active: &mut root::Active) -> io::Result<()> {
        let mut window = active
            .rpc
            .call(commands::Command::Window)?
            .as_object()
            .cloned()
            .ok_or_else(|| invalid("native usage window shape"))?;
        window.insert("operation".into(), serde_json::json!(operation));
        self.emit("usage_window", window)
    }
    pub(super) fn complete(&mut self) -> io::Result<()> {
        let token = self
            .final_token
            .clone()
            .ok_or_else(|| invalid("finite original cycle has no terminal Current"))?;
        self.emit(
            "complete",
            serde_json::json!({"root_pid":std::process::id(),"operation_count":self.operation_count,
            "final_owner_pid":self.final_owner_pid,"final_current_token":token}),
        )
    }
}

pub(super) fn retained_material(
    active: &root::Active,
    current: &CognitiveCheckpointReceipt,
) -> io::Result<codex_hepta_memory::VerifiedCognitiveMaterial> {
    let digest = codex_hepta_contracts::Sha256Digest::for_bytes(
        &serde_json::to_vec(&current.head.last_current).map_err(error)?,
    );
    let layout = HeptaFleetRoot::parse(active.archive.join(digest.as_str()))
        .map_err(error)?
        .layout()
        .agent(&current.head.owner_agent_id);
    runtime()?
        .block_on(CognitiveStore::verify_retained_root_material(
            &layout,
            &current.head.last_current,
        ))
        .map_err(error)
}
pub(super) fn material(
    active: &root::Active,
    current: &CognitiveCheckpointReceipt,
) -> io::Result<(std::path::PathBuf, String)> {
    let material = retained_material(active, current)?;
    material.verify_unchanged().map_err(error)?;
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(material.path())?;
    let mut hash = Sha256::new();
    let mut buffer = [0; 64 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
    }
    material.verify_unchanged().map_err(error)?;
    Ok((material.path().to_owned(), format!("{:x}", hash.finalize())))
}
fn process(pid: u32, role: u64) -> io::Result<serde_json::Value> {
    let status = std::fs::read_to_string(format!("/proc/{pid}/status"))?;
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    if status.len() > 16 * 1024 || stat.len() > 8192 {
        return Err(invalid("process observation bound"));
    }
    let field = |name: &str| -> io::Result<&str> {
        status
            .lines()
            .find_map(|line| line.strip_prefix(name))
            .map(str::trim)
            .ok_or_else(|| invalid(format!("missing actual {name}")))
    };
    let ids = |name: &str| -> io::Result<Vec<u32>> {
        field(name)?
            .split_whitespace()
            .map(|value| value.parse::<u32>().map_err(error))
            .collect()
    };
    let cap =
        |name: &str| -> io::Result<u64> { u64::from_str_radix(field(name)?, 16).map_err(error) };
    let fields = stat
        .rsplit_once(") ")
        .ok_or_else(|| invalid("actual process stat shape"))?
        .1
        .split_whitespace()
        .collect::<Vec<_>>();
    let ppid = fields
        .get(1)
        .ok_or_else(|| invalid("actual parent missing"))?
        .parse::<u32>()
        .map_err(error)?;
    let sid = unsafe { libc::getsid(pid as i32) };
    if sid < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(
        serde_json::json!({"role":role,"pid":pid,"ppid":ppid,"start_ticks":peer(pid,0)?.process_start_ticks,
        "uids":ids("Uid:")?,"gids":ids("Gid:")?,"groups":ids("Groups:")?,
        "caps":{"inheritable":cap("CapInh:")?,"permitted":cap("CapPrm:")?,"effective":cap("CapEff:")?,"bounding":cap("CapBnd:")?,"ambient":cap("CapAmb:")?},
        "nnp":field("NoNewPrivs:")?.parse::<u64>().map_err(error)?,"sid":sid}),
    )
}
fn root_denial(boot: &NativeBootstrap, opcode: u16) -> io::Result<u16> {
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open("/dev/hepta-control")?;
    let mut input = [0_u8; 104];
    input[..4].copy_from_slice(b"HOS2");
    input[4..6].copy_from_slice(&2_u16.to_le_bytes());
    input[8..10].copy_from_slice(&opcode.to_le_bytes());
    input[12..16].copy_from_slice(&64_u32.to_le_bytes());
    let payload = if opcode == 3 { 32_u32 } else { 40_u32 };
    input[16..20].copy_from_slice(&payload.to_le_bytes());
    input[24..32].copy_from_slice(&1_u64.to_le_bytes());
    input[40..48].copy_from_slice(&(if opcode == 3 { 2_u64 } else { 3_u64 }).to_le_bytes());
    input[48..56].copy_from_slice(&1_u64.to_le_bytes());
    if opcode == 3 {
        input[64..72].copy_from_slice(&1_u64.to_le_bytes());
        input[72..80].copy_from_slice(&100_000_000_u64.to_le_bytes());
        input[80..88].copy_from_slice(&25_000_000_u64.to_le_bytes());
    } else {
        input[64..80].copy_from_slice(&boot.id(96));
        input[80..96].copy_from_slice(&boot.id(112));
        input[96..104].copy_from_slice(&1_u64.to_le_bytes());
    }
    let mut output = [0; 128];
    let mut descriptor = [0_u8; 32];
    descriptor[..8].copy_from_slice(&(input.as_ptr() as u64).to_le_bytes());
    descriptor[8..16].copy_from_slice(&(output.as_mut_ptr() as u64).to_le_bytes());
    descriptor[16..20].copy_from_slice(&(64 + payload).to_le_bytes());
    descriptor[20..24].copy_from_slice(&128_u32.to_le_bytes());
    // Actual negative observation only: Root holds no management/history slot.
    // A non-denial fails this boot; it never becomes a writer effect receipt.
    if unsafe {
        libc::ioctl(
            file.as_raw_fd(),
            0xc020_4802 as libc::c_ulong,
            descriptor.as_mut_ptr(),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    let status = u16::from_le_bytes(output[10..12].try_into().unwrap());
    if &output[..4] != b"HOSR" || status != 2 {
        return Err(invalid(
            "Root unexpectedly obtained a native management/history capability",
        ));
    }
    Ok(status)
}
