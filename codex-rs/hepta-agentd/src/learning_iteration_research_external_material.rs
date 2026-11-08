//! Exact material checks for the private external-artifact research owner.
//! Finite actual training/evaluation evidence remains HOLD_NO_GO. No Product
//! OPE estimate, Parameter V3 eligibility, or production admission is inferred.

use std::collections::BTreeMap;
use std::ffi::CString;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::ensure;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Value;
use serde_json::json;

const MAX_FILE: u64 = 16 * 1024 * 1024;
const MAX_TOTAL: u64 = 64 * 1024 * 1024;

// Every component is opened relative to a held directory, with NOFOLLOW.
// There is no canonicalize-then-open race, and a FIFO cannot block a read.
fn open_at(dir: &File, name: &std::ffi::OsStr, flags: i32) -> std::io::Result<File> {
    let name = CString::new(name.as_bytes())?;
    // SAFETY: name is a live NUL-terminated string and dir owns its fd. A
    // successful openat returns a new descriptor uniquely owned by File.
    let fd = unsafe {
        libc::openat(
            dir.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
            0o600,
        )
    };
    if fd < 0 {
        return Err(std::io::Error::last_os_error());
    }
    // SAFETY: successful openat returned this uniquely owned descriptor.
    Ok(unsafe { File::from_raw_fd(fd) })
}

fn directory(path: &Path) -> anyhow::Result<File> {
    ensure!(path.is_absolute(), "absolute material path required");
    let mut fd = File::open("/")?;
    for component in path.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => fd = open_at(&fd, name, libc::O_RDONLY | libc::O_DIRECTORY)?,
            _ => anyhow::bail!("non-normal path component"),
        }
    }
    Ok(fd)
}

pub(super) struct Directory {
    path: PathBuf,
    file: File,
}

impl Directory {
    pub(super) fn create(path: PathBuf) -> anyhow::Result<Self> {
        let parent = directory(path.parent().context("directory parent")?)?;
        let name = path.file_name().context("directory name")?;
        match open_at(&parent, name, libc::O_RDONLY | libc::O_DIRECTORY) {
            Ok(file) => Ok(Self { path, file }),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let c_name = CString::new(name.as_bytes())?;
                // SAFETY: parent is a held directory; c_name is a live C string.
                ensure!(
                    unsafe { libc::mkdirat(parent.as_raw_fd(), c_name.as_ptr(), 0o700) } == 0,
                    "create-only research owner directory: {}",
                    std::io::Error::last_os_error()
                );
                parent.sync_all()?;
                let file = open_at(&parent, name, libc::O_RDONLY | libc::O_DIRECTORY)?;
                Ok(Self { path, file })
            }
            Err(error) => Err(error.into()),
        }
    }

    pub(super) fn require_linked(&self) -> anyhow::Result<()> {
        let a = self.file.metadata()?;
        let b = directory(&self.path)?.metadata()?;
        ensure!(
            (a.dev(), a.ino()) == (b.dev(), b.ino()),
            "owner directory replaced"
        );
        Ok(())
    }

    pub(super) fn optional(&self, name: &str) -> anyhow::Result<Option<Vec<u8>>> {
        ensure!(
            !name.contains('/') && !name.starts_with('.'),
            "owner entry name"
        );
        match open_at(&self.file, name.as_ref(), libc::O_RDONLY) {
            Ok(file) => Ok(Some(read_file(file, 1024 * 1024)?)),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    pub(super) fn read(&self, name: &str) -> anyhow::Result<Vec<u8>> {
        self.optional(name)?.context("missing durable owner entry")
    }

    pub(super) fn publish(&self, name: &str, bytes: &[u8]) -> anyhow::Result<()> {
        ensure!(
            !name.contains('/') && !name.starts_with('.') && bytes.len() <= 1024 * 1024,
            "owner publication bound"
        );
        let mut file = open_at(
            &self.file,
            name.as_ref(),
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL,
        )?;
        file.write_all(bytes)?;
        file.sync_all()?;
        self.file.sync_all()?;
        self.require_linked()?;
        ensure!(
            self.read(name)? == bytes,
            "owner publication readback differs"
        );
        Ok(())
    }
}

fn read_file(file: File, maximum: u64) -> anyhow::Result<Vec<u8>> {
    let before = file.metadata()?;
    ensure!(
        before.is_file() && before.nlink() == 1 && before.len() <= maximum,
        "regular, unaliased, bounded material required"
    );
    let mut bytes = Vec::new();
    (&file).take(maximum + 1).read_to_end(&mut bytes)?;
    let after = file.metadata()?;
    ensure!(
        bytes.len() as u64 == before.len()
            && before.len() == after.len()
            && before.mtime() == after.mtime()
            && before.mtime_nsec() == after.mtime_nsec()
            && before.ctime() == after.ctime()
            && before.ctime_nsec() == after.ctime_nsec(),
        "material changed during read"
    );
    Ok(bytes)
}

pub(super) fn digest(value: &Value) -> anyhow::Result<Digest32> {
    let text = value.as_str().context("digest string")?;
    ensure!(
        text.len() == 64
            && text
                .bytes()
                .all(|x| x.is_ascii_digit() || (b'a'..=b'f').contains(&x)),
        "canonical content digest"
    );
    let result: Digest32 = text.parse()?;
    ensure!(!result.is_zero(), "zero content digest");
    Ok(result)
}

pub(super) fn canonical(value: &Value) -> anyhow::Result<Vec<u8>> {
    fn sorted(v: &Value) -> Value {
        match v {
            Value::Array(a) => Value::Array(a.iter().map(sorted).collect()),
            Value::Object(o) => {
                let ordered: BTreeMap<_, _> =
                    o.iter().map(|(k, v)| (k.clone(), sorted(v))).collect();
                Value::Object(ordered.into_iter().collect())
            }
            _ => v.clone(),
        }
    }
    Ok(serde_json::to_vec(&sorted(value))?)
}

// serde_json::Value alone accepts duplicate object keys. Reject them at every
// nesting level, including safetensors headers and independently retained JSON.
pub(super) fn parse(bytes: &[u8]) -> anyhow::Result<Value> {
    struct Unique(Value);
    impl<'de> Deserialize<'de> for Unique {
        fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
            struct UniqueVisitor;
            impl<'de> Visitor<'de> for UniqueVisitor {
                type Value = Unique;
                fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                    f.write_str("JSON without duplicate object keys")
                }
                fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Unique, E> {
                    Ok(Unique(v.into()))
                }
                fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Unique, E> {
                    Ok(Unique(v.into()))
                }
                fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Unique, E> {
                    Ok(Unique(v.into()))
                }
                fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Unique, E> {
                    serde_json::Number::from_f64(v)
                        .map(|n| Unique(Value::Number(n)))
                        .ok_or_else(|| E::custom("nonfinite number"))
                }
                fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Unique, E> {
                    Ok(Unique(v.into()))
                }
                fn visit_unit<E: serde::de::Error>(self) -> Result<Unique, E> {
                    Ok(Unique(Value::Null))
                }
                fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Unique, A::Error> {
                    let mut values = Vec::new();
                    while let Some(Unique(v)) = a.next_element()? {
                        values.push(v);
                    }
                    Ok(Unique(Value::Array(values)))
                }
                fn visit_map<A: MapAccess<'de>>(self, mut a: A) -> Result<Unique, A::Error> {
                    let mut values = serde_json::Map::new();
                    while let Some((key, Unique(value))) = a.next_entry::<String, Unique>()? {
                        if values.insert(key, value).is_some() {
                            return Err(serde::de::Error::custom("duplicate JSON key"));
                        }
                    }
                    Ok(Unique(Value::Object(values)))
                }
            }
            d.deserialize_any(UniqueVisitor)
        }
    }
    Ok(serde_json::from_slice::<Unique>(bytes)?.0)
}

#[derive(Default)]
struct Inputs {
    pins: BTreeMap<String, Value>,
    bytes: u64,
}
impl Inputs {
    fn read(&mut self, path: &Path, maximum: u64) -> anyhow::Result<Vec<u8>> {
        let parent = directory(path.parent().context("material parent")?)?;
        let file = open_at(
            &parent,
            path.file_name().context("material filename")?,
            libc::O_RDONLY,
        )?;
        let raw = read_file(file, maximum.min(MAX_FILE))?;
        self.bytes = self
            .bytes
            .checked_add(raw.len() as u64)
            .context("material length overflow")?;
        ensure!(
            self.bytes <= MAX_TOTAL && self.pins.len() < 512,
            "research material total bound"
        );
        let pin = json!({"sha256":Digest32::of_bytes(&raw).to_string(),"bytes":raw.len()});
        if let Some(old) = self.pins.insert(
            path.to_str().context("UTF-8 material path")?.into(),
            pin.clone(),
        ) {
            ensure!(old == pin, "material changed between checks");
        }
        Ok(raw)
    }
    fn json(&mut self, path: &Path) -> anyhow::Result<Value> {
        parse(&self.read(path, MAX_FILE)?)
    }
    fn pinned(&mut self, reference: &Value, maximum: u64) -> anyhow::Result<Vec<u8>> {
        let path = Path::new(
            reference["path"]
                .as_str()
                .context("material reference path")?,
        );
        let raw = self.read(path, maximum)?;
        ensure!(
            Digest32::of_bytes(&raw) == digest(&reference["sha256"])?,
            "full-byte material pin"
        );
        for field in ["bytes", "byte_length"] {
            if let Some(size) = reference.get(field) {
                ensure!(size.as_u64() == Some(raw.len() as u64), "reference length");
            }
        }
        Ok(raw)
    }
}

fn uint(value: &Value) -> anyhow::Result<u64> {
    value.as_u64().context("unsigned integer")
}
fn text(value: &Value) -> anyhow::Result<&str> {
    value.as_str().context("string")
}
fn array(value: &Value) -> anyhow::Result<&[Value]> {
    Ok(value.as_array().context("array")?)
}

pub(super) fn require_unstarted(model: &Path) -> anyhow::Result<()> {
    let root = Directory::create(model.to_path_buf())?;
    for name in [
        "training-start.json",
        "native-training-admission.json",
        "train-result.json",
        "evaluate-result.json",
    ] {
        ensure!(
            root.optional(name)?.is_none(),
            "research owner must freeze before any training admission"
        );
    }
    Ok(())
}

pub(super) fn freeze(
    model: &Path,
    evidence: &Path,
    initial: &LearningIterationSnapshotV1,
) -> anyhow::Result<Value> {
    let mut inputs = Inputs::default();
    let frozen = inputs.json(&model.join("frozen.json"))?;
    let prepared = inputs.json(&model.join("prepare-result.json"))?;
    let request = &initial.request;
    let operation = request.operation_id.to_string();
    ensure!(
        frozen["schema"] == "hepta.research.smollm.frozen.v1"
            && frozen["research_profile"] == "external-trained-artifact-v1"
            && prepared["research_profile"] == frozen["research_profile"]
            && frozen["operation"] == operation
            && frozen["qualification"] == "HOLD_NO_GO"
            && frozen["independent_evaluation"] == false
            && frozen["prior_tasks_and_outcomes_exposed"] == true,
        "explicit research-only frozen profile"
    );
    ensure!(
        Path::new(text(&prepared["frozen"]["path"])?) == model.join("frozen.json"),
        "frozen path"
    );
    inputs.pinned(&prepared["frozen"], MAX_FILE)?;
    for key in [
        "parent",
        "dataset",
        "dataset_rows",
        "dataset_bytes",
        "model_config",
        "next_prompt",
    ] {
        ensure!(prepared[key] == frozen[key], "prepared/frozen field {key}");
    }
    ensure!(
        frozen["deadline_unix_seconds"] == request.envelope.expiry_unix_seconds
            && uint(&frozen["created_unix_ns"])? / 1_000_000_000
                < request.envelope.expiry_unix_seconds
            && frozen["steps"] == 10
            && frozen["cpu_threads"] == 4
            && frozen["maximum_training_seconds"] == 90
            && request.budget.maximum_training_steps == 10
            && request.budget.maximum_training_milliseconds == 90_000
            && request.budget.maximum_dataset_rows == 4
            && request.budget.maximum_dataset_bytes == 16_384
            && request.budget.maximum_artifact_bytes == 1_048_576
            && request.envelope.maximum_files == 1
            && request.envelope.maximum_diff_bytes == 1_048_576
            && request.envelope.maximum_candidates == 1
            && request.envelope.maximum_parallel_sandboxes == 1
            && request.envelope.grammar_digest
                == Digest32::of_bytes(b"original-smollm-10-step-lora-training-v1")
            && request.envelope.objective_digest == request.evaluation_profile
            && frozen["next_request_id"] == format!("{operation}-next-task"),
        "frozen task/budget binding"
    );
    let evaluation = array(&frozen["evaluation"])?;
    let expected = [
        ("4807 greater than 4806?", "yes"),
        ("5208 greater than 5209?", "no"),
        ("6311 greater than 6310?", "yes"),
        ("7402 greater than 7403?", "no"),
    ];
    ensure!(
        evaluation.len() == 4
            && frozen["evaluation_profile"] == "original-conditional-binary-raw-logit-q32-v1"
            && frozen["decision_rule"] == "candidate-correct-strictly-greater-else-NoUpdate"
            && frozen["next_prompt"] == "Answer with only yes or no. Is 8517 greater than 8516?",
        "fixed evaluation profile"
    );
    for (i, (row, (suffix, expected))) in evaluation.iter().zip(expected).enumerate() {
        ensure!(
            row == &json!({"prompt":format!("Answer with only yes or no. Is {suffix}"),
            "expected_output":expected,"request_id":format!("{operation}-eval-{i}")}),
            "frozen evaluation row"
        );
    }
    let profile = json!({"evaluation":evaluation,"rule":frozen["decision_rule"],"profile":frozen["evaluation_profile"]});
    ensure!(
        Digest32::of_bytes(&canonical(&profile)?) == request.evaluation_profile
            && digest(&prepared["evaluation_profile_sha256"])? == request.evaluation_profile,
        "native profile pin"
    );
    let dataset = inputs.pinned(&frozen["dataset"], request.budget.maximum_dataset_bytes)?;
    ensure!(
        dataset.len() as u64 == uint(&frozen["dataset_bytes"])?
            && array(&parse(&dataset)?["records"])?.len() == 4
            && frozen["dataset_rows"] == 4,
        "actual dataset bound"
    );
    ensure!(
        parse(&inputs.pinned(&frozen["parent_ref"], MAX_FILE)?)? == frozen["parent"],
        "original parent reference"
    );
    let parent = verify_material(
        &mut inputs,
        &frozen["parent"],
        request.budget.maximum_artifact_bytes,
    )?;
    ensure!(
        Digest32::of_bytes(&parent) == request.selected_artifact_digest
            && request.selected_bundle.components.cell_adapter
                == Some(digest(&frozen["parent"]["adapter"])?)
            && request.selected_bundle.components.composition
                == digest(&frozen["parent"]["contract"])?
            && request.selected_bundle.generation
                == codex_hepta_types::Generation::new(uint(&frozen["parent"]["generation"])?)?
            && request.selected_bundle.artifact_id.to_string() == format!("{operation}-retained"),
        "selected baseline material"
    );
    let expected_components = CellBundleComponentsV1 {
        base: digest(&prepared["model_config"]["material_manifest_sha256"])?,
        organ_adapter: None,
        cell_adapter: Some(digest(&frozen["parent"]["adapter"])?),
        heads: Digest32::of_bytes(b"yes:10407,no:4607/raw-logit-q32"),
        composition: digest(&frozen["parent"]["contract"])?,
        encoder: digest(&prepared["model_config"]["material_manifest_sha256"])?,
        tokenizer: digest(&prepared["model_config"]["material_manifest_sha256"])?,
        normalizer: Digest32::of_bytes(b"identity-no-model-normalization-v1"),
        calibration: request.evaluation_profile,
        numeric_profile: digest(&prepared["helper_sha256"])?,
        output_schema: Digest32::of_bytes(b"hepta.research.smollm.actual-proposal.v1"),
        state_schema: Digest32::of_bytes(b"research-stateless-conditional-binary-input.v1"),
        state_semantics: Digest32::of_bytes(
            b"complete-input-retention-no-hidden-recurrent-state-v1",
        ),
    };
    ensure!(
        request.selected_bundle.components == expected_components
            && request.selected_bundle.training_lineage.is_none()
            && request.selected_bundle.rollback_predecessor.is_none()
            && prepared["worker_sha256"]
                == "10c09efcb24d65ce850ccbee61f3034262fa026ee5d19adab90bc9eda67049c0"
            && prepared["helper_sha256"]
                == "185e747bb90e4c793ea9c2bc0ce8606f88780d7154873e153a902f4da4e2ee4e",
        "full native baseline and original worker/helper profile"
    );
    for (key, parent_key) in [
        ("parent_adapter", "adapter"),
        ("parent_contract", "contract"),
        ("parent_file_sha256", "file_sha256"),
        ("parent_dir", "directory"),
        ("generation", "generation"),
    ] {
        ensure!(
            frozen["model_config"][key] == frozen["parent"][parent_key],
            "frozen model parent binding"
        );
    }
    let source = frozen["source_before"]
        .as_object()
        .context("source closure")?;
    ensure!(
        !source.is_empty() && source.len() <= 256,
        "source closure bound"
    );
    for (path, hash) in source {
        ensure!(
            Digest32::of_bytes(&inputs.read(Path::new(path), MAX_FILE)?) == digest(hash)?,
            "frozen source changed"
        );
    }
    for (relative, hash) in frozen["model_config"]["source_pins"]
        .as_object()
        .context("model source pins")?
    {
        let path = Path::new(text(&frozen["model_config"]["source_dir"])?).join(relative);
        ensure!(
            source.get(path.to_str().context("source pin path")?) == Some(hash),
            "model source absent from full closure"
        );
    }
    ensure!(
        canonical(&frozen["source_before"])?.is_ascii()
            && Digest32::of_bytes(&canonical(&frozen["source_before"])?)
                == digest(&prepared["source_digest"])?,
        "source closure digest"
    );
    let task = inputs.read(&evidence.join("source-task-receipt.json"), MAX_FILE)?;
    let task_value = parse(&task)?;
    ensure!(
        Digest32::of_bytes(&task) == request.completed_task_receipt
            && task_value["operation_id"] == format!("{operation}-source-task")
            && task_value["disposition"] == "stopped",
        "original completed source task"
    );
    inputs.read(&evidence.join("source-use-delivered.json"), MAX_FILE)?;
    Ok(
        json!({"schema":"hepta.research.external-trained-artifact.frozen-inputs.v1",
        "files":inputs.pins,"frozen_sha256":prepared["frozen"]["sha256"],
        "source_digest":prepared["source_digest"],"dataset":frozen["dataset"]["sha256"]}),
    )
}

fn pon_hash(tag: &str, raw: &[u8]) -> Digest32 {
    let mut bytes = b"TRNM-PON1\0".to_vec();
    bytes.extend_from_slice(&(tag.len() as u16).to_le_bytes());
    bytes.extend_from_slice(tag.as_bytes());
    bytes.extend_from_slice(&(raw.len() as u32).to_le_bytes());
    bytes.extend_from_slice(raw);
    Digest32::of_bytes(&bytes)
}

struct Tensor<'a> {
    dtype: String,
    shape: Vec<u64>,
    raw: &'a [u8],
}
fn tensors(raw: &[u8]) -> anyhow::Result<BTreeMap<String, Tensor<'_>>> {
    ensure!(raw.len() >= 10, "tensor header length");
    let header = usize::try_from(u64::from_le_bytes(raw[..8].try_into()?))?;
    ensure!(
        (2..=1024 * 1024).contains(&header) && header + 8 <= raw.len(),
        "tensor header bound"
    );
    let value = parse(&raw[8..8 + header])?;
    let payload = &raw[8 + header..];
    let mut tensors = BTreeMap::new();
    let mut intervals = Vec::new();
    for (name, value) in value.as_object().context("tensor object")? {
        if name == "__metadata__" {
            ensure!(
                value
                    .as_object()
                    .context("tensor metadata")?
                    .values()
                    .all(Value::is_string),
                "tensor metadata strings"
            );
            continue;
        }
        ensure!(
            value.as_object().context("tensor fields")?.len() == 3,
            "closed tensor fields"
        );
        let dtype = text(&value["dtype"])?;
        let width = match dtype {
            "F32" => 4,
            "I64" => 8,
            "BOOL" => 1,
            _ => anyhow::bail!("unsupported tensor dtype"),
        };
        let shape = array(&value["shape"])?
            .iter()
            .map(uint)
            .collect::<anyhow::Result<Vec<_>>>()?;
        ensure!(
            !shape.is_empty() && shape.len() <= 4 && shape.iter().all(|&d| d > 0),
            "tensor shape"
        );
        let length = shape
            .iter()
            .try_fold(width, |a: u64, b| a.checked_mul(*b))
            .context("tensor size overflow")?;
        let offsets = array(&value["data_offsets"])?;
        ensure!(offsets.len() == 2, "tensor offsets");
        let start = usize::try_from(uint(&offsets[0])?)?;
        let end = usize::try_from(uint(&offsets[1])?)?;
        ensure!(
            start < end && end <= payload.len() && (end - start) as u64 == length,
            "tensor range"
        );
        let raw = &payload[start..end];
        if dtype == "F32" {
            ensure!(
                raw.chunks_exact(4)
                    .all(|b| f32::from_le_bytes(b.try_into().expect("four bytes")).is_finite()),
                "nonfinite tensor"
            );
        }
        if dtype == "BOOL" {
            ensure!(raw.iter().all(|b| *b <= 1), "boolean tensor");
        }
        intervals.push((start, end));
        tensors.insert(
            name.clone(),
            Tensor {
                dtype: dtype.into(),
                shape,
                raw,
            },
        );
    }
    intervals.sort_unstable();
    let mut cursor = 0;
    for (start, end) in intervals {
        ensure!(start == cursor, "tensor overlap/hole");
        cursor = end;
    }
    ensure!(cursor == payload.len(), "tensor trailing bytes");
    Ok(tensors)
}

fn verify_material(inputs: &mut Inputs, material: &Value, limit: u64) -> anyhow::Result<Vec<u8>> {
    ensure!(
        material["schema"] == "hepta-smollm-parent-material-v1"
            && material.as_object().context("material object")?.len() == 7,
        "closed parent material"
    );
    let root = Path::new(text(&material["directory"])?);
    let raw = inputs.read(&root.join("artifact.safetensors"), limit)?;
    let contract_raw = inputs.read(&root.join("target-contract.json"), 2 * 1024 * 1024)?;
    let wrapper_raw = inputs.read(&root.join("wrapped-adapter.json"), 2 * 1024 * 1024)?;
    let contract = parse(&contract_raw)?;
    let wrapper = parse(&wrapper_raw)?;
    ensure!(
        canonical(&contract)? == contract_raw
            && canonical(&wrapper)? == wrapper_raw
            && pon_hash("target-decoder-adapter-contract-v1", &contract_raw)
                == digest(&material["contract"])?
            && pon_hash("wrapped-decoder-lora-material-v1", &wrapper_raw)
                == digest(&material["adapter"])?
            && Digest32::of_bytes(&raw) == digest(&material["file_sha256"])?,
        "original contract/adapter/full artifact identity"
    );
    ensure!(
        wrapper["schema"] == "pon-wrapped-decoder-lora-material-v1"
            && wrapper["contract"] == material["contract"]
            && wrapper["material_scope"]
                == "factor-bytes-and-insertion-interface-not-functional-equivalence",
        "wrapper scope"
    );
    let factors = tensors(&raw)?;
    let targets = array(&contract["targets"])?;
    let modules = wrapper["modules"].as_object().context("factor modules")?;
    ensure!(
        factors.len() == 120 && targets.len() == 60 && modules.len() == 60,
        "fixed SmolLM factor set"
    );
    for layer in 0..30 {
        for projection in ["q_proj", "v_proj"] {
            let name = format!("model.layers.{layer}.self_attn.{projection}");
            let out = if projection == "q_proj" { 576 } else { 192 };
            let target =
                json!({"module":name,"in_features":576,"out_features":out,"rank":4,"alpha":[8,1]});
            ensure!(
                targets.iter().filter(|t| *t == &target).count() == 1,
                "exact factor target"
            );
            let module = modules.get(&name).context("missing factor module")?;
            ensure!(
                module["rank"] == 4
                    && module["alpha"] == json!([8, 1])
                    && module["dropout"] == false,
                "factor scale"
            );
            for (factor, shape) in [("A", vec![4, 576]), ("B", vec![out, 4])] {
                let tensor = factors
                    .get(&format!("{name}.{factor}"))
                    .context("missing factor")?;
                ensure!(
                    tensor.dtype == "F32"
                        && tensor.shape == shape
                        && module[factor]
                            == json!({"dtype":"float32","shape":shape,
                        "byte_length":tensor.raw.len(),"sha256":Digest32::of_bytes(tensor.raw).to_string()}),
                    "factor bytes/interface binding"
                );
            }
        }
    }
    Ok(raw)
}

pub(super) fn verify(
    model: &Path,
    evidence: &Path,
    snapshot: &LearningIterationSnapshotV1,
    genesis: Digest32,
    frozen_pins: &Value,
    owner_created_ns: u64,
) -> anyhow::Result<Value> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    ensure!(
        snapshot.receipts.len() == 4
            && coordinator.next_stage() == Some(LearningIterationStageV1::Proposal),
        "only a complete Qualified training/evaluation prefix can propose"
    );
    let request = &snapshot.request;
    let operation = request.operation_id.to_string();
    let mut inputs = Inputs::default();
    let frozen = inputs.json(&model.join("frozen.json"))?;
    let trained = inputs.json(&model.join("train-result.json"))?;
    let evaluated = inputs.json(&model.join("evaluate-result.json"))?;
    let before = inputs.json(&evidence.join("native-before-training.json"))?;
    ensure!(
        before["operation"] == operation
            && before["initial_learning_head"] == genesis.to_string()
            && before["evaluation_profile"] == request.evaluation_profile.to_string()
            && before["frozen_plan_sha256"] == frozen_pins["frozen_sha256"]
            && before["absolute_deadline_unix_seconds"] == request.envelope.expiry_unix_seconds
            && before["maximum_training_milliseconds"]
                == request.budget.maximum_training_milliseconds
            && before["envelope_git_digest_encoding"]
                == "sha256-canonical-lowercase-git-object-id-text",
        "native admission frozen context"
    );
    for (field, expected) in [
        ("source_commit", request.envelope.base_commit),
        ("source_tree", request.envelope.base_tree),
    ] {
        let id = text(&before[field])?;
        ensure!(
            id.len() == 40
                && id
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                && Digest32::of_bytes(id.as_bytes()) == expected,
            "actual native source identity"
        );
    }
    let before_time = uint(&before["created_unix_seconds"])?;
    ensure!(
        before_time >= uint(&frozen["created_unix_ns"])? / 1_000_000_000
            && before_time < request.envelope.expiry_unix_seconds,
        "native before-training time"
    );
    let episode =
        Digest32::of_bytes(&inputs.read(&evidence.join("source-use-delivered.json"), MAX_FILE)?);
    let dataset = &frozen["dataset"];
    let experience = &snapshot.receipts[0];
    let data_receipt = &snapshot.receipts[1];
    ensure!(
        experience.observation
            == LearningIterationObservationV1::Experience {
                episode_digest: episode,
                completed_task_receipt: request.completed_task_receipt
            },
        "source-task/experience binding"
    );
    ensure!(
        data_receipt.observation
            == LearningIterationObservationV1::Dataset {
                snapshot_digest: digest(&dataset["sha256"])?,
                episode_digest: episode,
                withdrawal_frontier: Digest32::of_bytes(
                    b"public-synthetic-research-source-no-private-subjects-v1"
                ),
                rows: 4,
                bytes: uint(&frozen["dataset_bytes"])?
            },
        "native dataset binding"
    );
    for (name, receipt) in [
        ("experience.json", experience),
        ("dataset.json", data_receipt),
        ("train-result.json", &snapshot.receipts[2]),
        ("evaluate-result.json", &snapshot.receipts[3]),
    ] {
        let root = if name.ends_with("-result.json") {
            model
        } else {
            evidence
        };
        ensure!(
            Digest32::of_bytes(&inputs.read(&root.join(name), MAX_FILE)?)
                == receipt.evidence_digest,
            "actual bytes differ from authenticated native stage evidence"
        );
    }
    let mut through_dataset =
        LearningIterationCoordinatorV1::new(request.clone(), snapshot.owners.clone())?;
    through_dataset.record(experience.clone(), experience.observed_unix_seconds)?;
    through_dataset.record(data_receipt.clone(), data_receipt.observed_unix_seconds)?;
    let admission = inputs.json(&model.join("native-training-admission.json"))?;
    ensure!(
        admission
            == json!({"schema":"hepta.research.smollm.process.v1","action":"train",
        "operation":operation,"deadline_unix_seconds":request.envelope.expiry_unix_seconds,
        "frozen_sha256":frozen_pins["frozen_sha256"],"initial_learning_head":genesis.to_string(),
        "dataset_learning_head":through_dataset.snapshot().head_digest.to_string()}),
        "original native training admission"
    );
    ensure!(
        inputs.json(&evidence.join("process-02-train.request.json"))? == admission,
        "train process input differs"
    );
    for action in ["02-train", "03-evaluate"] {
        let exit = inputs.json(&evidence.join(format!("process-{action}.exit.json")))?;
        let completed = uint(&exit["completed_unix_seconds"])?;
        ensure!(
            exit["exit_code"] == 0
                && uint(&exit["pid"])? > 0
                && exit["absolute_unix_deadline"] == request.envelope.expiry_unix_seconds
                && completed >= before_time
                && completed < request.envelope.expiry_unix_seconds,
            "real process did not complete inside original absolute budget"
        );
    }
    ensure!(
        inputs.json(&evidence.join("process-03-evaluate.request.json"))?
            == json!({
        "schema":"hepta.research.smollm.process.v1","action":"evaluate","operation":operation,
        "deadline_unix_seconds":request.envelope.expiry_unix_seconds,"frozen_sha256":frozen_pins["frozen_sha256"]}),
        "evaluation process original frozen request"
    );
    let candidate_material = inputs.json(&model.join("training/worker/parent-material.json"))?;
    let candidate_bytes = verify_material(
        &mut inputs,
        &candidate_material,
        request.budget.maximum_artifact_bytes,
    )?;
    let candidate_sha = Digest32::of_bytes(&candidate_bytes);
    ensure!(
        trained["candidate"] == candidate_material
            && evaluated["candidate"] == candidate_material
            && candidate_material["operation_id"] == format!("{operation}-train")
            && Path::new(text(&candidate_material["directory"])?) == model.join("training/worker")
            && candidate_sha != request.selected_artifact_digest
            && candidate_material["contract"] == frozen["parent"]["contract"]
            && uint(&candidate_material["generation"])?
                == uint(&frozen["parent"]["generation"])?
                    .checked_add(1)
                    .context("generation overflow")?,
        "new actual candidate/operation/parent generation"
    );
    let mut candidate = request.selected_bundle.clone();
    candidate.artifact_id = StableId::new(format!("{operation}-trained"))?;
    candidate.generation = candidate.generation.next()?;
    candidate.components.cell_adapter = Some(digest(&candidate_material["adapter"])?);
    candidate.components.composition = digest(&candidate_material["contract"])?;
    candidate.rollback_predecessor = Some(request.selected_bundle.digest()?);
    candidate.training_lineage = Some(CellTrainingLineageV1 {
        source_bundle: request.selected_bundle.digest()?,
        dataset: digest(&dataset["sha256"])?,
        update_rule: digest(&frozen_pins["source_digest"])?,
        evaluation_profile: request.evaluation_profile,
    });
    ensure!(
        coordinator.candidate() == Some(&candidate),
        "full native candidate bundle differs"
    );
    let milliseconds = uint(&trained["milliseconds"])?;
    ensure!(
        milliseconds > 0
            && milliseconds <= request.budget.maximum_training_milliseconds
            && trained["steps"] == 10
            && trained["artifact_bytes"] == candidate_bytes.len()
            && trained["dataset_sha256"] == dataset["sha256"]
            && trained["source_digest"] == frozen_pins["source_digest"]
            && trained["actual_loaded_parent"] == frozen["parent"]["adapter"],
        "training budgets/lineage"
    );
    ensure!(
        snapshot.receipts[2].observation
            == LearningIterationObservationV1::Training {
                candidate: Box::new(candidate.clone()),
                steps: 10,
                milliseconds,
                artifact_bytes: candidate_bytes.len() as u64
            },
        "native training metrics differ from actual receipt"
    );
    let command = inputs.json(&model.join("training-command.json"))?;
    let training_start = inputs.json(&model.join("training-start.json"))?;
    let frozen_at = uint(&frozen["created_unix_ns"])?;
    let native_at = uint(&before["created_unix_ns"])?;
    let started_at = uint(&training_start["started_unix_ns"])?;
    let completed_at = uint(&command["completed_unix_ns"])?;
    let deadline_ns = request
        .envelope
        .expiry_unix_seconds
        .checked_mul(1_000_000_000)
        .context("deadline ns overflow")?;
    ensure!(
        training_start["schema"] == "hepta.research.smollm.training-start.v1"
            && training_start["operation"] == operation
            && training_start["frozen_sha256"] == frozen_pins["frozen_sha256"]
            && digest(&training_start["native_admission_sha256"])?
                == Digest32::of_bytes(
                    &inputs.read(&model.join("native-training-admission.json"), MAX_FILE)?
                )
            && frozen_at <= owner_created_ns
            && owner_created_ns <= native_at
            && native_at <= started_at
            && started_at < completed_at
            && completed_at < deadline_ns
            && command["started_unix_ns"] == started_at,
        "actual frozen/native admission/child-start/completion clock ordering"
    );
    let argv = array(&command["command"])?;
    ensure!(
        !argv.is_empty() && Path::new(text(&argv[0])?).is_absolute(),
        "explicit training executable"
    );
    let expected_argv = json!([
        argv[0],
        Path::new(text(&frozen["model_config"]["source_dir"])?)
            .join("scripts/llm_inherited_runtime.py"),
        "train",
        "--materials",
        frozen["model_config"]["materials_dir"],
        "--output",
        model.join("training"),
        "--operation-id",
        format!("{operation}-train"),
        "--input",
        dataset["path"],
        "--input-sha256",
        dataset["sha256"],
        "--threads",
        "4",
        "--steps",
        "10",
        "--parent",
        frozen["parent_ref"]["path"],
        "--parent-sha256",
        frozen["parent_ref"]["sha256"]
    ]);
    ensure!(
        command["command"] == expected_argv
            && command["returncode"] == 0
            && command["milliseconds"] == milliseconds,
        "actual original trainer command/budget"
    );
    ensure!(
        Path::new(text(&trained["receipt"]["path"])?)
            == model.join("training/worker/actual-receipt.json"),
        "original training receipt path"
    );
    let training = parse(&inputs.pinned(&trained["receipt"], MAX_FILE)?)?;
    ensure!(
        training["schema"] == "hepta-smollm-inherited-execution-v1"
            && training["scope"] == "actual-inherited-execution-no-owner-admission"
            && training["phase"] == "train"
            && training["operation_id"] == format!("{operation}-train")
            && training["outcome"] == "success"
            && training["disposition"] == "candidate-produced"
            && training["parameter_change"] == true
            && training["actual_backend"] == "cpu"
            && training["actual_loaded_parent"] == frozen["parent"]["adapter"]
            && training["parent"] == frozen["parent"]
            && training["artifact"] == candidate_material["adapter"]
            && training["contract"] == candidate_material["contract"]
            && training["generation"] == candidate_material["generation"]
            && training["input_sha256"] == dataset["sha256"]
            && training["training"]["steps"] == 10
            && array(&training["training"]["loss"])?.len() == 10
            && training["authority"]
                == json!({"hepta_final_use":false,"independent_accepted":false,
            "installation_authorized":false,"prospective_accepted":false,"public_reward_eligible":false,"selection_authorized":false}),
        "actual trainer receipt cannot confer another owner authority"
    );
    for loss in array(&training["training"]["loss"])? {
        let loss: f64 = text(loss)?.parse()?;
        ensure!(
            loss.is_finite() && loss >= 0.0,
            "actual optimizer loss sequence"
        );
    }
    for (name, hash) in training["source_pins"]
        .as_object()
        .context("trainer source pins")?
    {
        ensure!(
            frozen["source_before"]
                .as_object()
                .context("source closure")?
                .iter()
                .filter(|(path, value)| Path::new(path)
                    .file_name()
                    .is_some_and(|n| n == name.as_str())
                    && *value == hash)
                .count()
                == 1,
            "trainer source differs from original frozen full closure"
        );
    }
    let supervisor = inputs.json(&model.join("training/worker/supervisor.json"))?;
    ensure!(
        supervisor["exit_code"] == 0
            && supervisor["outcome"] == "success"
            && supervisor["owned_child_exit_observed"] == true
            && supervisor["owned_child_reap_resolved"] == true
            && supervisor["waited_child_reaped"] == true
            && supervisor["stop_reason"].is_null(),
        "owned training process terminal evidence"
    );
    let cost_raw = inputs.read(&model.join("training/worker/cost-events.jsonl"), MAX_FILE)?;
    let costs = cost_raw
        .split(|b| *b == b'\n')
        .filter(|s| !s.is_empty())
        .map(parse)
        .collect::<anyhow::Result<Vec<_>>>()?;
    ensure!(
        costs.len() == 9
            && costs.iter().all(|event| event["outcome"] == "success")
            && training["cost_events"] == json!(costs),
        "complete actual training cost event stream"
    );
    let scores = evaluate(&mut inputs, model, &frozen, &candidate_material, &evaluated)?;
    ensure!(
        scores[1] > scores[0]
            && evaluated["disposition"] == "Qualified"
            && evaluated["selected_adapter"] == candidate_material["adapter"]
            && evaluated["frozen_sha256"] == frozen_pins["frozen_sha256"],
        "strict real-output improvement required"
    );
    ensure!(
        snapshot.receipts[3].observation
            == LearningIterationObservationV1::Evaluation {
                candidate_bundle: candidate.digest()?,
                evaluation_profile: request.evaluation_profile,
                disposition: LearningEvaluationDispositionV1::Qualified
            },
        "native evaluation binding"
    );
    Ok(
        json!({"schema":"hepta.research.external-trained-artifact.material.v1",
        "genesis":genesis.to_string(),"predecessor":snapshot.head_digest.to_string(),
        "owner_created_unix_ns":owner_created_ns,
        "candidate_bundle":candidate.digest()?.to_string(),"candidate_file_sha256":candidate_sha.to_string(),
        "frozen_inputs":frozen_pins,"files":inputs.pins,"parent_correct":scores[0],"candidate_correct":scores[1],
        "evaluation_count":4,"scope":"fixed-exposed-four-prompt-local-output-comparison",
        "qualification":"HOLD_NO_GO","independent_evaluation":false}),
    )
}

fn evaluate(
    inputs: &mut Inputs,
    model: &Path,
    frozen: &Value,
    candidate: &Value,
    result: &Value,
) -> anyhow::Result<[u64; 2]> {
    let roles = array(&result["evaluations"])?;
    ensure!(roles.len() == 2, "exactly both model evaluations");
    let mut totals = [0, 0];
    for (index, (role, material)) in [("parent", &frozen["parent"]), ("candidate", candidate)]
        .into_iter()
        .enumerate()
    {
        let rows = array(&roles[index]["rows"])?;
        ensure!(
            roles[index]["role"] == role
                && roles[index]["adapter"] == material["adapter"]
                && rows.len() == 4,
            "complete parent/candidate role"
        );
        let raw = inputs.read(&model.join(format!("{role}-eval.jsonl")), MAX_FILE)?;
        let transcript = raw
            .split(|b| *b == b'\n')
            .filter(|s| !s.is_empty())
            .map(parse)
            .collect::<anyhow::Result<Vec<_>>>()?;
        ensure!(transcript.len() == 12, "complete actual worker transcript");
        for pair in transcript.chunks_exact(2) {
            ensure!(
                pair[0]["direction"] == "send"
                    && pair[1]["direction"] == "receive"
                    && pair[1]["message"]["ok"] == true
                    && pair[0]["message"]["id"] == pair[1]["message"]["id"],
                "worker request/response framing"
            );
        }
        let sent = &transcript[0]["message"];
        let opened = &transcript[1]["message"]["result"];
        let session = format!("{}-{role}-eval", text(&frozen["operation"])?);
        ensure!(
            sent["op"] == "open"
                && sent["session_id"] == session
                && sent["params"]["output_root"]
                    == model
                        .join(format!("{role}-eval-store"))
                        .to_str()
                        .context("store path")?
                && sent["params"]["model"]["parent_adapter"] == material["adapter"]
                && sent["params"]["model"]["parent_contract"] == material["contract"]
                && sent["params"]["model"]["parent_file_sha256"] == material["file_sha256"]
                && sent["params"]["model"]["parent_dir"] == material["directory"]
                && sent["params"]["model"]["generation"] == material["generation"]
                && sent["params"]["limits"]["max_forward_examples"] == 4,
            "actual evaluated model loading context"
        );
        let identity = &opened["model"]["identity"];
        for key in ["adapter", "contract", "file_sha256", "generation"] {
            ensure!(
                identity["parent"][key] == material[key],
                "opened model parent identity"
            );
        }
        ensure!(
            identity["material_preflight"]["result"] == "PASS"
                && identity["material_preflight"]["file_sha256"] == material["file_sha256"]
                && identity["material_manifest_sha256"]
                    == frozen["model_config"]["material_manifest_sha256"],
            "actual load material preflight"
        );
        for (i, row) in rows.iter().enumerate() {
            let frozen_row = &frozen["evaluation"][i];
            let request = &transcript[2 + i * 2]["message"];
            let response = &transcript[3 + i * 2]["message"]["result"];
            ensure!(
                request["op"] == "probe"
                    && request["session_id"] == session
                    && request["params"]["inputs"]
                        == json!({"mode":"conditional_binary",
                    "prompt":frozen_row["prompt"],"request_id":frozen_row["request_id"]})
                    && response["session_id"] == session
                    && response["outputs"] == row["artifact"]
                    && response["evidence"] == row["evidence"],
                "original actual probe response"
            );
            for key in ["artifact", "evidence"] {
                ensure!(
                    Path::new(text(&row[key]["path"])?).parent()
                        == Some(model.join(format!("{role}-eval-store")).as_path()),
                    "foreign evaluation material path"
                );
            }
            let probe = parse(&inputs.pinned(&row["evidence"], MAX_FILE)?)?;
            ensure!(
                probe["schema"] == "hepta.weight.evidence.v1"
                    && probe["mode"] == "DEVELOPMENT_OBSERVATION"
                    && probe["session_id"] == session
                    && probe["model_id"] == opened["model_id"]
                    && probe["input_spec"] == request["params"]["inputs"]
                    && probe["outputs"] == row["artifact"]
                    && probe["input"]["encoded_input_id"] == row["encoded_input_id"]
                    && probe["input"]["model_input_id"] == row["model_input_id"]
                    && probe["computation"]["action_token_ids"] == json!([10407, 4607])
                    && probe["computation"]["model_forward_calls"] == 1
                    && probe["total_forward_examples"] == i + 1
                    && probe["gradient_steps"] == 0
                    && probe["optimizer_calls"] == 0,
                "actual model-specific output evidence"
            );
            let raw = inputs.pinned(&row["artifact"], 1024 * 1024)?;
            let tensors = tensors(&raw)?;
            ensure!(
                tensors.len() == 6
                    && [
                        "next_token_logits",
                        "input_ids",
                        "attention_mask",
                        "raw_action_logits",
                        "scores_q32",
                        "conditional_binary_probabilities"
                    ]
                    .iter()
                    .all(|name| tensors.contains_key(*name)),
                "complete output tensor set"
            );
            let ids = tensors.get("input_ids").context("actual input tokens")?;
            let mask = tensors
                .get("attention_mask")
                .context("actual attention mask")?;
            let probabilities = tensors
                .get("conditional_binary_probabilities")
                .context("derived binary probabilities")?;
            ensure!(
                ids.dtype == "I64"
                    && ids.shape.len() == 2
                    && ids.shape[0] == 1
                    && ids.shape[1] <= 128
                    && mask.dtype == "BOOL"
                    && mask.shape == ids.shape
                    && mask.raw.iter().all(|b| *b == 1)
                    && probabilities.dtype == "F32"
                    && probabilities.shape == [1, 2],
                "complete bounded output interface"
            );
            for token in ids.raw.chunks_exact(8) {
                ensure!(
                    (0..49152).contains(&i64::from_le_bytes(token.try_into()?)),
                    "input token vocabulary"
                );
            }
            let logits = tensors.get("next_token_logits").context("raw logits")?;
            let actions = tensors.get("raw_action_logits").context("action logits")?;
            let scores = tensors.get("scores_q32").context("raw scores")?;
            ensure!(
                logits.dtype == "F32"
                    && logits.shape == [1, 49152]
                    && actions.dtype == "F32"
                    && actions.shape == [1, 2]
                    && scores.dtype == "I64"
                    && scores.shape == [1, 2]
                    && Digest32::of_bytes(logits.raw) == digest(&row["logits_sha256"])?
                    && probe["computation"]["logits_sha256"] == row["logits_sha256"]
                    && Digest32::of_bytes(&raw) == digest(&row["output_sha256"])?,
                "original logits/score byte binding"
            );
            let mut actual = [0i64; 2];
            for (j, token) in [10407usize, 4607].into_iter().enumerate() {
                let raw_action = &actions.raw[j * 4..j * 4 + 4];
                ensure!(
                    raw_action == &logits.raw[token * 4..token * 4 + 4],
                    "raw score selects wrong vocabulary token"
                );
                let scaled =
                    f64::from(f32::from_le_bytes(raw_action.try_into()?)) * 4_294_967_296.0;
                ensure!(
                    scaled >= i64::MIN as f64 && scaled < 9_223_372_036_854_775_808.0,
                    "Q32 range"
                );
                actual[j] = i64::from_le_bytes(scores.raw[j * 8..j * 8 + 8].try_into()?);
                ensure!(
                    actual[j] == scaled.round_ties_even() as i64,
                    "raw float32 to Q32 score"
                );
            }
            let predicted = if actual[0] >= actual[1] { "yes" } else { "no" };
            let correct = frozen_row["expected_output"] == predicted;
            ensure!(
                row["scores_q32"] == json!(actual)
                    && row["predicted_output"] == predicted
                    && row["correct"] == correct
                    && row["expected_output"] == frozen_row["expected_output"]
                    && row["request_id"] == frozen_row["request_id"]
                    && digest(&row["prompt_sha256"])?
                        == Digest32::of_bytes(text(&frozen_row["prompt"])?.as_bytes())
                    && row["model_forward_calls"] == 1
                    && row["total_forward_examples"] == i + 1,
                "recomputed raw-output decision differs"
            );
            totals[index] += u64::from(correct);
        }
        ensure!(
            roles[index]["correct"] == totals[index]
                && transcript[10]["message"]["op"] == "close"
                && transcript[11]["message"]["result"]["forward_examples"] == 4
                && transcript[11]["message"]["result"]["patch_candidates"] == 0,
            "complete unchanged evaluation run"
        );
        let exit = inputs.json(&model.join(format!("{role}-eval-exit.json")))?;
        ensure!(
            exit["exit_code"] == 0 && exit["terminated_by"] == "controlled-stdio-EOF",
            "evaluation worker exit"
        );
    }
    Ok(totals)
}

#[path = "learning_iteration_research_external_material_tests.rs"]
mod tests;
