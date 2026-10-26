//! Reconstruct the original narrow TCM1/TCR1 bytes from measured payloads.
//! Exact comparison rejects all untrusted counts/tails without allocating from them.
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use codex_hepta_types::Digest32;
use sha2::Digest;
use sha2::Sha256;

use super::need;

const CHUNK: usize = 1024 * 1024;

type MeasuredPayloadParts = (u64, Digest32, Vec<(u32, Digest32)>);

pub(super) enum ManifestKind {
    Cell,
    Release,
}

pub(super) fn verify(
    kind: ManifestKind,
    text: &str,
    expected: &[u8],
    declared: &str,
) -> Result<Digest32, String> {
    need(
        unhex(text)? == expected,
        "exact manifest wire/context/chunks/roster",
    )?;
    let domain: &[u8] = match kind {
        ManifestKind::Cell => b"trnm.cell-manifest.v1\0",
        ManifestKind::Release => b"trnm.cell-release-manifest.v1\0",
    };
    let id = Digest32::of_parts(&[domain, expected]);
    need(declared == id.to_string(), "manifest domain identity")?;
    Ok(id)
}

pub(super) fn open_regular(path: &Path, maximum: u64) -> Result<File, String> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|e| e.to_string())?;
    let meta = file.metadata().map_err(|e| e.to_string())?;
    need(
        meta.is_file() && meta.len() > 0 && meta.len() <= maximum,
        "material size/type",
    )?;
    Ok(file)
}

pub(super) fn measure(mut input: impl Read, maximum: u64) -> Result<MeasuredPayloadParts, String> {
    let mut scratch = vec![0; CHUNK];
    let mut whole = Sha256::new();
    let mut chunks = Vec::new();
    let mut total = 0_u64;
    loop {
        let mut used = 0;
        while used < CHUNK {
            let count = match input.read(&mut scratch[used..]) {
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                result => result.map_err(|e| e.to_string())?,
            };
            if count == 0 {
                break;
            }
            used += count;
            total = total
                .checked_add(count as u64)
                .ok_or("material size overflow")?;
            need(total <= maximum, "material size bound")?;
        }
        if used == 0 {
            break;
        }
        whole.update(&scratch[..used]);
        chunks.push((used as u32, Digest32::of_bytes(&scratch[..used])));
        if used < CHUNK {
            break;
        }
    }
    need(total > 0, "empty material")?;
    Ok((total, Digest32::from_array(whole.finalize().into()), chunks))
}

pub(super) fn context(family: &str, digests: [Digest32; 5]) -> Result<Vec<u8>, String> {
    need(
        !family.is_empty()
            && family.len() <= 64
            && family
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            && digests.iter().all(|d| !d.is_zero()),
        "transport context",
    )?;
    let mut out = vec![family.len() as u8];
    out.extend_from_slice(family.as_bytes());
    for d in digests {
        out.extend_from_slice(d.as_array());
    }
    Ok(out)
}

pub(super) fn manifest(
    context: &[u8],
    size: u64,
    sha: Digest32,
    chunks: &[(u32, Digest32)],
) -> Vec<u8> {
    let mut out = b"TCM1".to_vec();
    out.extend_from_slice(context);
    out.extend_from_slice(&size.to_be_bytes());
    out.extend_from_slice(sha.as_array());
    out.extend_from_slice(&(CHUNK as u32).to_be_bytes());
    out.extend_from_slice(&(chunks.len() as u32).to_be_bytes());
    for (size, sha) in chunks {
        out.extend_from_slice(&size.to_be_bytes());
        out.extend_from_slice(sha.as_array());
    }
    out
}

pub(super) fn release(context: &[u8], ids: &[Digest32]) -> Vec<u8> {
    let mut out = b"TCR1".to_vec();
    out.extend_from_slice(context);
    out.extend_from_slice(&(ids.len() as u32).to_be_bytes());
    for id in ids {
        out.extend_from_slice(id.as_array());
    }
    out
}

pub(super) fn unhex(text: &str) -> Result<Vec<u8>, String> {
    need(
        text.len() <= 32_768 && text.len().is_multiple_of(2),
        "manifest hex length",
    )?;
    fn nibble(b: u8) -> Result<u8, String> {
        match b {
            b'0'..=b'9' => Ok(b - b'0'),
            b'a'..=b'f' => Ok(b - b'a' + 10),
            _ => Err("manifest lowercase hex".to_owned()),
        }
    }
    text.as_bytes()
        .chunks_exact(2)
        .map(|p| Ok((nibble(p[0])? << 4) | nibble(p[1])?))
        .collect()
}
