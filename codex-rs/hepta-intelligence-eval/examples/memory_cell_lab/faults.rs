//! Filesystem-backed fault model for qualification, NOT a production store.
//! Mutating calls require the harness's OS flock. A separate control file models
//! the current owner fence/revocation frontier and is never restored from a cell backup.
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Crash { Never, BeforePublish, AfterPublish }

fn atom(s: &str) -> bool {
    !s.is_empty() && s.len() <= 128 && s.bytes().all(|b| b.is_ascii_alphanumeric() || b"_:.-".contains(&b)) && s != "-"
}
fn list(s: &str) -> Result<BTreeSet<String>, String> {
    if s == "-" { return Ok(BTreeSet::new()); }
    let mut result = BTreeSet::new();
    for item in s.split(',') {
        if !atom(item) || !result.insert(item.to_owned()) { return Err("invalid/duplicate identity".into()); }
    }
    if result.len() > 1024 { return Err("identity limit".into()); }
    Ok(result)
}
fn joined(items: &BTreeSet<String>) -> String {
    if items.is_empty() { "-".into() } else { items.iter().cloned().collect::<Vec<_>>().join(",") }
}
fn integer(s: &str) -> Result<u64, String> { s.parse().map_err(|_| "invalid integer".into()) }

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Artifact {
    pub roots: BTreeSet<String>,
    pub parents: BTreeSet<String>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Snapshot {
    pub epoch: u64,
    pub revision: u64,
    pub graph_generation: u64,
    pub active: BTreeSet<String>,
    pub pending: BTreeSet<String>,
    pub artifacts: BTreeMap<String, Artifact>,
    pub operations: BTreeMap<String, (String, u64)>,
}
impl Snapshot {
    fn encode(&self) -> String {
        let mut out = format!("MCELL-NODE-LAB-1\n{}|{}|{}\n{}\n{}\n", self.epoch, self.revision,
            self.graph_generation, joined(&self.active), joined(&self.pending));
        for (id, a) in &self.artifacts { out.push_str(&format!("A|{id}|{}|{}\n", joined(&a.roots), joined(&a.parents))); }
        for (id, (semantic, rev)) in &self.operations { out.push_str(&format!("O|{id}|{rev}|{semantic}\n")); }
        out
    }
    fn decode(bytes: &str) -> Result<Self, String> {
        if bytes.len() > 4 * 1024 * 1024 { return Err("snapshot byte limit".into()); }
        let mut lines = bytes.lines();
        if lines.next() != Some("MCELL-NODE-LAB-1") { return Err("snapshot version".into()); }
        let head: Vec<_> = lines.next().ok_or("snapshot header")?.split('|').collect();
        if head.len() != 3 { return Err("snapshot header shape".into()); }
        let mut state = Self { epoch: integer(head[0])?, revision: integer(head[1])?, graph_generation: integer(head[2])?,
            active: list(lines.next().ok_or("active")?)?, pending: list(lines.next().ok_or("pending")?)?,
            artifacts: BTreeMap::new(), operations: BTreeMap::new() };
        if state.epoch == 0 { return Err("zero epoch".into()); }
        for line in lines {
            let f: Vec<_> = line.split('|').collect();
            if f.len() != 4 || !atom(f[1]) { return Err("snapshot record shape".into()); }
            match f[0] {
                "A" => {
                    let a = Artifact { roots: list(f[2])?, parents: list(f[3])? };
                    if a.roots.is_empty() || state.artifacts.insert(f[1].into(), a).is_some() { return Err("invalid artifact".into()); }
                }
                "O" => {
                    let command = Operation::parse(f[3])?;
                    let revision = integer(f[2])?;
                    if command.id != f[1] || revision == 0 || revision > state.revision
                        || state.operations.insert(f[1].into(), (f[3].into(), revision)).is_some() { return Err("invalid receipt".into()); }
                }
                _ => return Err("unknown snapshot record".into()),
            }
        }
        if state.artifacts.len() > 1024 || state.operations.len() > 1024 { return Err("record limit".into()); }
        for id in state.active.iter().chain(&state.pending) {
            if !state.artifacts.contains_key(id) { return Err("dangling graph node".into()); }
        }
        for (id, a) in &state.artifacts {
            for parent in &a.parents {
                let prior = state.artifacts.get(parent).ok_or("dangling lineage")?;
                if id == parent || !prior.roots.is_subset(&a.roots) { return Err("severed lineage".into()); }
            }
        }
        Ok(state)
    }
}

#[derive(Clone, Debug)]
pub struct Operation {
    pub kind: String,
    pub id: String,
    pub epoch: u64,
    pub expected_revision: u64,
    pub nodes: BTreeSet<String>,
    pub roots: BTreeSet<String>,
    pub parents: BTreeSet<String>,
    canonical: String,
}
impl Operation {
    pub fn parse(text: &str) -> Result<Self, String> {
        if text.len() > 32_768 { return Err("operation byte limit".into()); }
        let f: Vec<_> = text.split('~').collect();
        if f.len() != 7 || !atom(f[1]) { return Err("operation shape".into()); }
        let op = Self { kind: f[0].into(), id: f[1].into(), epoch: integer(f[2])?,
            expected_revision: integer(f[3])?, nodes: list(f[4])?, roots: list(f[5])?,
            parents: list(f[6])?, canonical: text.into() };
        let shape = match op.kind.as_str() {
            "publish" => op.nodes.len() == 1,
            "prepare-split" => op.nodes.len() == 2 && !op.parents.is_empty(),
            "commit-split" | "abort" => op.nodes.is_empty() && op.roots.is_empty() && op.parents.is_empty(),
            _ => false,
        };
        if !shape || op.epoch == 0 { return Err("operation kind/fields".into()); }
        Ok(op)
    }
}

fn write_atomic(root: &Path, name: &str, data: &str, crash: Crash) -> Result<(), String> {
    if data.len() > 4 * 1024 * 1024 { return Err("write byte limit".into()); }
    let temp = root.join(format!("{name}.next"));
    let mut file = File::create(&temp).map_err(|e| e.to_string())?;
    file.write_all(data.as_bytes()).and_then(|_| file.sync_all()).map_err(|e| e.to_string())?;
    if crash == Crash::BeforePublish { std::process::exit(86); }
    fs::rename(temp, root.join(name)).map_err(|e| e.to_string())?;
    File::open(root).and_then(|f| f.sync_all()).map_err(|e| e.to_string())?;
    if crash == Crash::AfterPublish { std::process::exit(87); }
    Ok(())
}

pub struct LabNode { root: PathBuf }
impl LabNode {
    pub fn bootstrap(root: &Path) -> Result<Self, String> {
        fs::create_dir(root).map_err(|e| e.to_string())?;
        let node = Self { root: root.into() };
        write_atomic(root, "control", "MCELL-CONTROL-LAB-1\n1\n-\n", Crash::Never)?;
        let state = Snapshot { epoch: 1, revision: 0, graph_generation: 0, active: BTreeSet::new(),
            pending: BTreeSet::new(), artifacts: BTreeMap::new(), operations: BTreeMap::new() };
        write_atomic(root, "snapshot", &state.encode(), Crash::Never)?;
        Ok(node)
    }
    pub fn open(root: &Path) -> Self { Self { root: root.into() } }
    fn control(&self) -> Result<(u64, BTreeSet<String>), String> {
        let bytes = fs::read_to_string(self.root.join("control")).map_err(|e| e.to_string())?;
        let lines: Vec<_> = bytes.lines().collect();
        if lines.len() != 3 || lines[0] != "MCELL-CONTROL-LAB-1" { return Err("control shape".into()); }
        Ok((integer(lines[1])?, list(lines[2])?))
    }
    fn load(&self) -> Result<Snapshot, String> {
        let bytes = fs::read_to_string(self.root.join("snapshot")).map_err(|e| e.to_string())?;
        Snapshot::decode(&bytes)
    }
    pub fn read(&self) -> Result<Snapshot, String> {
        let (epoch, revoked) = self.control()?;
        let state = self.load()?;
        if state.epoch != epoch { return Err("fenced restore".into()); }
        for id in &state.active {
            if !state.artifacts[id].roots.is_disjoint(&revoked) { return Err("revoked descendant".into()); }
        }
        Ok(state)
    }
    pub fn apply(&self, op: &Operation, crash: Crash) -> Result<u64, String> {
        let (epoch, revoked) = self.control()?;
        let mut state = self.load()?;
        if op.epoch != epoch || state.epoch != epoch { return Err("fenced writer".into()); }
        if let Some((semantic, rev)) = state.operations.get(&op.id) {
            if semantic != &op.canonical { return Err("operation identity conflict".into()); }
            return Ok(*rev);
        }
        if op.expected_revision != state.revision { return Err("checkpoint CAS conflict".into()); }
        if state.operations.len() >= 1024 { return Err("operation capacity".into()); }
        match op.kind.as_str() {
            "publish" | "prepare-split" => {
                if !state.pending.is_empty() { return Err("pending topology".into()); }
                if state.artifacts.len() + op.nodes.len() > 1024 { return Err("artifact capacity".into()); }
                if op.kind == "prepare-split" && op.parents != state.active { return Err("split predecessor mismatch".into()); }
                let mut roots = op.roots.clone();
                for parent in &op.parents { roots.extend(state.artifacts.get(parent).ok_or("missing parent")?.roots.iter().cloned()); }
                if roots.is_empty() || roots.len() > 1024 || !roots.is_disjoint(&revoked) { return Err("unsupported/revoked training lineage".into()); }
                for id in &op.nodes {
                    if state.artifacts.contains_key(id) { return Err("immutable artifact conflict".into()); }
                    state.artifacts.insert(id.clone(), Artifact { roots: roots.clone(), parents: op.parents.clone() });
                }
                if op.kind == "publish" {
                    state.active = op.nodes.clone();
                    state.graph_generation = state.graph_generation.checked_add(1).ok_or("generation overflow")?;
                } else { state.pending = op.nodes.clone(); }
            }
            "commit-split" => {
                if state.pending.len() != 2 { return Err("no prepared split".into()); }
                for id in &state.pending {
                    if !state.artifacts[id].roots.is_disjoint(&revoked) { return Err("revoked pending update".into()); }
                }
                state.active = std::mem::take(&mut state.pending);
                state.graph_generation = state.graph_generation.checked_add(1).ok_or("generation overflow")?;
            }
            "abort" => { state.pending.clear(); }
            _ => return Err("unknown operation".into()),
        }
        state.revision = state.revision.checked_add(1).ok_or("revision overflow")?;
        state.operations.insert(op.id.clone(), (op.canonical.clone(), state.revision));
        write_atomic(&self.root, "snapshot", &state.encode(), crash)?;
        Ok(state.revision)
    }
    pub fn revoke(&self, expected_epoch: u64, root: &str) -> Result<(), String> {
        if !atom(root) { return Err("invalid revocation root".into()); }
        let (epoch, mut revoked) = self.control()?;
        if epoch != expected_epoch { return Err("fenced revocation".into()); }
        revoked.insert(root.into());
        if revoked.len() > 1024 { return Err("revocation capacity".into()); }
        write_atomic(&self.root, "control", &format!("MCELL-CONTROL-LAB-1\n{epoch}\n{}\n", joined(&revoked)), Crash::Never)
    }
    pub fn migrate(&self, expected_epoch: u64) -> Result<(), String> {
        let (epoch, revoked) = self.control()?;
        let mut state = self.load()?;
        if epoch != expected_epoch || state.epoch != epoch { return Err("migration fence".into()); }
        let next = epoch.checked_add(1).ok_or("epoch overflow")?;
        // A crash between these writes makes reads unavailable, never old-writer eligible.
        write_atomic(&self.root, "control", &format!("MCELL-CONTROL-LAB-1\n{next}\n{}\n", joined(&revoked)), Crash::Never)?;
        state.epoch = next;
        state.pending.clear();
        write_atomic(&self.root, "snapshot", &state.encode(), Crash::Never)
    }
    pub fn reconcile_migration(&self, expected_epoch: u64) -> Result<(), String> {
        let (epoch, _) = self.control()?;
        let mut state = self.load()?;
        if epoch != expected_epoch || state.epoch.checked_add(1) != Some(epoch) { return Err("recovery fence".into()); }
        state.epoch = epoch;
        state.pending.clear();
        write_atomic(&self.root, "snapshot", &state.encode(), Crash::Never)
    }
}
