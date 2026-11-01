//! Model-bound deterministic memory checkpoints (no owner authorization).

use crate::q24_core::{Memory, Outcome, Probability};
use crate::q24_sha256::digest;
#[cfg(unix)]
use std::fs::File;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

const MAGIC: &[u8; 8] = b"HQ24CK03";

pub fn encode(memory: &Memory, model: &[u8; 32]) -> Outcome<Vec<u8>> {
    memory.validate()?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(model);
    bytes.extend_from_slice(&(memory.addresses.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&(memory.addresses[0].counts.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&memory.completed.to_le_bytes());
    bytes.extend_from_slice(&memory.clock_ticks.to_le_bytes());
    for address in &memory.addresses {
        bytes.extend_from_slice(&address.error_units.to_le_bytes());
        for count in &address.counts {
            bytes.extend_from_slice(&count.to_le_bytes());
        }
        for chunk in address.support.chunks(8) {
            let packed = chunk
                .iter()
                .enumerate()
                .fold(0u8, |bits, (index, possible)| {
                    bits | (u8::from(*possible) << index)
                });
            bytes.push(packed);
        }
    }
    bytes.extend_from_slice(&digest(&bytes));
    Ok(bytes)
}

pub fn decode(bytes: &[u8], model: &[u8; 32], addresses: usize, states: usize) -> Outcome<Memory> {
    if addresses == 0 || addresses > 64 || states == 0 || states > 512 {
        return Err("unsupported checkpoint dimensions");
    }
    let support_bytes = states.div_ceil(8);
    if bytes.len() != 96 + addresses * (4 + 4 * states + support_bytes) || &bytes[..8] != MAGIC {
        return Err("checkpoint schema or length mismatch");
    }
    let body_end = bytes.len() - 32;
    if digest(&bytes[..body_end]) != bytes[body_end..] {
        return Err("checkpoint checksum mismatch");
    }
    if &bytes[8..40] != model {
        return Err("checkpoint model mismatch");
    }
    let stored_addresses = u32::from_le_bytes(bytes[40..44].try_into().unwrap()) as usize;
    let stored_states = u32::from_le_bytes(bytes[44..48].try_into().unwrap()) as usize;
    if stored_addresses != addresses || stored_states != states {
        return Err("checkpoint dimension mismatch");
    }
    let completed = u64::from_le_bytes(bytes[48..56].try_into().unwrap());
    let clock_ticks = u64::from_le_bytes(bytes[56..64].try_into().unwrap());
    let mut offset = 64;
    let mut restored = Vec::with_capacity(addresses);
    for _ in 0..addresses {
        let error_units = u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap());
        offset += 4;
        let mut counts = Vec::with_capacity(states);
        for _ in 0..states {
            counts.push(u32::from_le_bytes(
                bytes[offset..offset + 4].try_into().unwrap(),
            ));
            offset += 4;
        }
        let packed = &bytes[offset..offset + support_bytes];
        if states % 8 != 0 && packed[support_bytes - 1] >> (states % 8) != 0 {
            return Err("invalid support padding");
        }
        let support = (0..states)
            .map(|index| packed[index / 8] & (1 << (index % 8)) != 0)
            .collect();
        offset += support_bytes;
        restored.push(Probability {
            counts,
            support,
            error_units,
        });
    }
    let result = Memory {
        addresses: restored,
        completed,
        clock_ticks,
    };
    result.validate()?;
    Ok(result)
}

pub fn save(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    fs::create_dir_all(parent)?;
    let temporary = path.with_extension(format!("tmp.{}", std::process::id()));
    let result = (|| {
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        output.write_all(bytes)?;
        output.sync_all()?;
        drop(output);
        fs::rename(&temporary, path)?;
        #[cfg(unix)]
        File::open(parent)?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}
