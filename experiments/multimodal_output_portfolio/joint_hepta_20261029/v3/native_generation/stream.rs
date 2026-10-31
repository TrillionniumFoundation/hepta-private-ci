//! Append-only native output prefixes and independent-process recovery.
//! A local Linux research owner; not a replacement for production Agentd.
use crate::codec::{Packet, Result, gif, immutable_write, png, sha256, sync_dir, wav};
use crate::math::{normal, sigmoid, uniform};
use crate::model::{MODALITIES, Model, State};
use std::fs::{self, File, OpenOptions};
use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};

unsafe extern "C" {
    fn flock(fd: i32, operation: i32) -> i32;
}
pub struct Lock {
    _file: File,
}
impl Lock {
    pub fn take(dir: &Path) -> Result<Self> {
        let path = dir.join("writer.lock");
        if fs::symlink_metadata(&path).is_ok_and(|m| !m.file_type().is_file()) {
            return Err("invalid lock path".into());
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
            .map_err(|e| e.to_string())?;
        if unsafe { flock(file.as_raw_fd(), 2 | 4) } != 0 {
            return Err("concurrent native writer".into());
        }
        Ok(Self { _file: file })
    }
}
pub struct Session {
    pub record: Packet,
    pub state: State,
    pub head: String,
    pub sequence: usize,
}
fn integer(p: &Packet, key: &str) -> Result<usize> {
    p.text(key)?.parse::<usize>().map_err(|e| e.to_string())
}
fn prefix(p: &Packet, m: &str) -> Result<Vec<u8>> {
    p.get(&format!("prefix.{m}"))?
        .iter()
        .map(|v| {
            if (0.0..=255.0).contains(v) && v.fract() == 0.0 {
                Ok(*v as u8)
            } else {
                Err("prefix byte domain".into())
            }
        })
        .collect()
}
fn total(m: &str) -> Result<usize> {
    match m {
        "image" => Ok(16),
        "audio" => Ok(1024),
        "video" => Ok(4),
        "text" => Ok(2),
        _ => Err("unknown modality".into()),
    }
}
fn byte_range(m: &str, start: usize, count: usize) -> Result<std::ops::Range<usize>> {
    let size = match m {
        "image" => 48,
        "audio" => 2,
        "video" => 768,
        _ => return Err("variable byte modality".into()),
    };
    Ok(start * size..(start + count) * size)
}
fn sample_bytes(
    model: &Model,
    state: &State,
    modality: &str,
    seed: u64,
    sampler: &str,
) -> Result<Vec<u8>> {
    let i = MODALITIES
        .iter()
        .position(|m| *m == modality)
        .ok_or("unknown modality")?;
    let out = model.outputs(state)?;
    let values = &out[i];
    let seed = seed ^ ((state.steps as u64) << 32) ^ ((i as u64) << 48);
    if modality == "text" {
        let mut labels = Vec::new();
        for (k, logits) in [&values[..63], &values[63..]].iter().enumerate() {
            let maximum = logits.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            let weights: Vec<f64> = logits.iter().map(|v| (v - maximum).exp()).collect();
            let chosen = if sampler == "mean" {
                logits.iter().position(|v| *v == maximum).unwrap()
            } else {
                let threshold = uniform(seed, k as u64) * weights.iter().sum::<f64>();
                let mut accumulated = 0.0;
                let mut selected = weights.len() - 1;
                for (j, v) in weights.iter().enumerate() {
                    accumulated += v;
                    if accumulated >= threshold {
                        selected = j;
                        break;
                    }
                }
                selected
            };
            labels.push(chosen as u8);
        }
        return Ok(labels);
    }
    let sampled: Vec<f64> = values
        .iter()
        .enumerate()
        .map(|(j, v)| {
            let x = *v
                + if sampler == "mean" {
                    0.0
                } else {
                    0.035 * normal(seed, j as u64)
                };
            if modality == "audio" {
                x.tanh()
            } else {
                sigmoid(x)
            }
        })
        .collect();
    if modality == "audio" {
        return Ok(sampled
            .iter()
            .flat_map(|v| ((v.clamp(-1.0, 1.0) * 32767.0).round_ties_even() as i16).to_le_bytes())
            .collect());
    }
    let frames = if modality == "video" { 4 } else { 1 };
    let mut bytes = Vec::with_capacity(sampled.len());
    for frame in 0..frames {
        for pixel in 0..256 {
            for channel in 0..3 {
                bytes.push(
                    (sampled[frame * 768 + channel * 256 + pixel] * 255.0).round_ties_even() as u8,
                );
            }
        }
    }
    Ok(bytes)
}
fn committed_chunk(
    model: &Model,
    s: &State,
    prior: &Packet,
    m: &str,
    count: usize,
) -> Result<Vec<u8>> {
    let start = integer(prior, &format!("cursor.{m}"))?;
    if count == 0
        || start
            .checked_add(count)
            .is_none_or(|end| end > total(m).unwrap_or(0))
    {
        return Err("commit range exceeds remaining output".into());
    }
    let seed = prior
        .text("seed")?
        .parse::<u64>()
        .map_err(|e| e.to_string())?;
    let all = sample_bytes(model, s, m, seed, prior.text("sampler")?)?;
    if m == "text" {
        let mut out = Vec::new();
        for (index, label) in all.iter().enumerate().skip(start).take(count) {
            out.extend(
                if index == 0 {
                    format!("action={label};")
                } else {
                    format!("sound={label}\n")
                }
                .as_bytes(),
            );
        }
        Ok(out)
    } else {
        Ok(all[byte_range(m, start, count)?].to_vec())
    }
}
fn next_packet(
    model: &Model,
    public: &Packet,
    previous: &Session,
    op: &str,
    arg: &str,
    count: usize,
) -> Result<(Packet, Vec<u8>)> {
    let state = match op {
        "step" => model.advance(&previous.state, arg, public)?,
        "commit" => previous.state.clone(),
        _ => return Err("unknown operation".into()),
    };
    let mut p = state.packet();
    for key in ["weights", "input", "seed", "sampler"] {
        p.meta.insert(key.into(), previous.record.text(key)?.into());
    }
    p.meta
        .insert("kind".into(), "joint-native-stream-v3".into());
    p.meta
        .insert("sequence".into(), (previous.sequence + 1).to_string());
    p.meta.insert("previous".into(), previous.head.clone());
    p.meta.insert("operation".into(), op.into());
    p.meta.insert("argument".into(), arg.into());
    p.meta.insert("count".into(), count.to_string());
    for m in MODALITIES {
        p.meta.insert(
            format!("cursor.{m}"),
            previous.record.text(&format!("cursor.{m}"))?.into(),
        );
        p.vector(
            &format!("prefix.{m}"),
            previous.record.get(&format!("prefix.{m}"))?.to_vec(),
        );
    }
    let mut chunk = Vec::new();
    if op == "commit" {
        chunk = committed_chunk(model, &state, &previous.record, arg, count)?;
        let start = integer(&previous.record, &format!("cursor.{arg}"))?;
        p.meta
            .insert(format!("cursor.{arg}"), (start + count).to_string());
        p.meta.insert("chunk".into(), sha256(&chunk));
        let mut bytes = prefix(&previous.record, arg)?;
        bytes.extend(&chunk);
        p.vector(
            &format!("prefix.{arg}"),
            bytes.into_iter().map(f64::from).collect(),
        );
    }
    Ok((p, chunk))
}
fn initial(
    model: &Model,
    public: &Packet,
    weights_hash: &str,
    input_hash: &str,
    seed: u64,
    sampler: &str,
) -> Result<Packet> {
    if !["mean", "splitmix-normal-v1"].contains(&sampler) {
        return Err("unknown emission law".into());
    }
    let mut p = model.encode(public)?.packet();
    p.meta.extend([
        ("kind".into(), "joint-native-stream-v3".into()),
        ("weights".into(), weights_hash.into()),
        ("input".into(), input_hash.into()),
        ("seed".into(), seed.to_string()),
        ("sampler".into(), sampler.into()),
        ("sequence".into(), "0".into()),
        ("previous".into(), "0".repeat(64)),
        ("operation".into(), "init".into()),
        ("argument".into(), "".into()),
        ("count".into(), "0".into()),
    ]);
    for m in MODALITIES {
        p.meta.insert(format!("cursor.{m}"), "0".into());
        p.vector(&format!("prefix.{m}"), Vec::new());
    }
    Ok(p)
}
fn publish(dir: &Path, p: &Packet) -> Result<String> {
    let bytes = p.encode()?;
    let seq = integer(p, "sequence")?;
    let tmp = dir.join(format!("events/.pending-{}-{seq}", std::process::id()));
    immutable_write(&tmp, &bytes)?;
    let dest = dir.join(format!("events/{seq:08}.hps"));
    fs::hard_link(&tmp, &dest).map_err(|e| e.to_string())?;
    sync_dir(&dir.join("events"))?;
    fs::remove_file(tmp).map_err(|e| e.to_string())?;
    Ok(sha256(&bytes))
}
pub fn create(
    dir: &Path,
    model: &Model,
    public: &Packet,
    weights_hash: &str,
    input_hash: &str,
    seed: u64,
    sampler: &str,
) -> Result<Session> {
    fs::create_dir(dir).map_err(|e| e.to_string())?;
    let _lock = Lock::take(dir)?;
    fs::create_dir(dir.join("events")).map_err(|e| e.to_string())?;
    fs::create_dir(dir.join("chunks")).map_err(|e| e.to_string())?;
    let record = initial(model, public, weights_hash, input_hash, seed, sampler)?;
    let state = State::read(&record, model)?;
    let head = publish(dir, &record)?;
    sync_dir(dir)?;
    Ok(Session {
        record,
        state,
        head,
        sequence: 0,
    })
}
pub fn load(
    dir: &Path,
    model: &Model,
    public: &Packet,
    weights_hash: &str,
    input_hash: &str,
) -> Result<Session> {
    if !fs::symlink_metadata(dir)
        .map_err(|e| e.to_string())?
        .file_type()
        .is_dir()
    {
        return Err("invalid session directory".into());
    }
    let mut paths: Vec<PathBuf> = fs::read_dir(dir.join("events"))
        .map_err(|e| e.to_string())?
        .map(|entry| entry.map(|e| e.path()).map_err(|e| e.to_string()))
        .collect::<Result<_>>()?;
    paths.retain(|p| p.extension().is_some_and(|v| v == "hps"));
    paths.sort();
    if paths.is_empty() || paths.len() > 256 {
        return Err("invalid journal count".into());
    }
    let mut prior: Option<Session> = None;
    for (index, path) in paths.iter().enumerate() {
        if path.file_name().and_then(|s| s.to_str()) != Some(format!("{index:08}.hps").as_str()) {
            return Err("journal gap or reordered event".into());
        }
        let p = Packet::read(path)?;
        if p.text("weights")? != weights_hash || p.text("input")? != input_hash {
            return Err("model/input identity drift".into());
        }
        let expected = if let Some(previous) = &prior {
            let (expected, chunk) = next_packet(
                model,
                public,
                previous,
                p.text("operation")?,
                p.text("argument")?,
                integer(&p, "count")?,
            )?;
            if !chunk.is_empty() {
                let filename = dir.join(format!("chunks/{}.bin", sha256(&chunk)));
                let metadata = fs::symlink_metadata(&filename).map_err(|e| e.to_string())?;
                if !metadata.file_type().is_file()
                    || fs::read(filename).map_err(|e| e.to_string())? != chunk
                {
                    return Err("committed chunk missing or changed".into());
                }
            }
            expected
        } else {
            initial(
                model,
                public,
                weights_hash,
                input_hash,
                p.text("seed")?.parse::<u64>().map_err(|e| e.to_string())?,
                p.text("sampler")?,
            )?
        };
        if p.encode()? != expected.encode()? {
            return Err("journal semantic replay mismatch".into());
        }
        let bytes = p.encode()?;
        let state = State::read(&p, model)?;
        prior = Some(Session {
            record: p,
            state,
            head: sha256(&bytes),
            sequence: index,
        });
    }
    prior.ok_or("empty journal".into())
}
pub fn mutate(
    dir: &Path,
    model: &Model,
    public: &Packet,
    weights_hash: &str,
    input_hash: &str,
    expected: &str,
    op: &str,
    arg: &str,
    count: usize,
    fault: &str,
) -> Result<Session> {
    let _lock = Lock::take(dir)?;
    let previous = load(dir, model, public, weights_hash, input_hash)?;
    if previous.head != expected {
        return Err("stale expected predecessor".into());
    }
    if previous.sequence >= 255 {
        return Err("journal capacity".into());
    }
    let (record, chunk) = next_packet(model, public, &previous, op, arg, count)?;
    if !chunk.is_empty() {
        let filename = dir.join(format!("chunks/{}.bin", sha256(&chunk)));
        if filename.exists() {
            if fs::read(&filename).map_err(|e| e.to_string())? != chunk {
                return Err("chunk identity conflict".into());
            }
        } else {
            immutable_write(&filename, &chunk)?;
        }
        sync_dir(&dir.join("chunks"))?;
    }
    if fault == "after_chunk" {
        std::process::exit(75);
    }
    let head = publish(dir, &record)?;
    if fault == "after_event" {
        std::process::exit(76);
    }
    let state = State::read(&record, model)?;
    Ok(Session {
        record,
        state,
        head,
        sequence: previous.sequence + 1,
    })
}
pub fn export(
    dir: &Path,
    session: &Session,
    out: &Path,
    rate: u32,
    frame_ms: u16,
) -> Result<String> {
    if !session.state.stopped
        || MODALITIES
            .iter()
            .any(|m| integer(&session.record, &format!("cursor.{m}")).ok() != total(m).ok())
    {
        return Err("export requires STOP and complete prefixes".into());
    }
    fs::create_dir(out).map_err(|e| e.to_string())?;
    let image = png(&prefix(&session.record, "image")?)?;
    let audio = wav(&prefix(&session.record, "audio")?, rate)?;
    let video = gif(&prefix(&session.record, "video")?, frame_ms)?;
    let text = prefix(&session.record, "text")?;
    let mut entries = Vec::new();
    for (name, bytes) in [
        ("image.png", image),
        ("audio.wav", audio),
        ("video.gif", video),
        ("text.txt", text),
    ] {
        immutable_write(&out.join(name), &bytes)?;
        entries.push(format!("\"{name}\":\"{}\"", sha256(&bytes)));
    }
    let manifest = format!(
        "{{\"schema\":\"hepta.native-stream-bundle.v3\",\"model\":\"{}\",\"input\":\"{}\",\"journal_head\":\"{}\",\"sampler\":\"{}\",\"files\":{{{}}}}}\n",
        session.record.text("weights")?,
        session.record.text("input")?,
        session.head,
        session.record.text("sampler")?,
        entries.join(",")
    );
    immutable_write(&out.join("MANIFEST.json"), manifest.as_bytes())?;
    sync_dir(out)?;
    let _ = dir;
    Ok(manifest)
}
