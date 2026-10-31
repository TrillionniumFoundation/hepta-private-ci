//! Native checks of all emitted file identities and the exact presentation clock.
//! Full MP4 decode is a pinned host observer operation; this module does not claim it.
use crate::stream_io::Result;
use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use std::path::Path;

pub fn checked(path: &str, expected: &str) -> Result<Vec<u8>> {
    let path = Path::new(path);
    let meta = std::fs::symlink_metadata(path)?;
    if !meta.is_file() || meta.file_type().is_symlink() || meta.len() == 0 || meta.len() > 4_000_000
    {
        return Err("Invalid bounded actual media file".into());
    }
    let bytes = std::fs::read(path)?;
    if Digest32::of_bytes(&bytes).to_string() != expected {
        return Err("Actual media bytes changed".into());
    }
    Ok(bytes)
}

fn little16(bytes: &[u8], at: usize) -> Result<u16> {
    Ok(u16::from_le_bytes(
        bytes.get(at..at + 2).ok_or("Truncated WAV")?.try_into()?,
    ))
}
fn little32(bytes: &[u8], at: usize) -> Result<u32> {
    Ok(u32::from_le_bytes(
        bytes.get(at..at + 4).ok_or("Truncated WAV")?.try_into()?,
    ))
}

pub fn validate(receipt: &Value) -> Result<Value> {
    let media = receipt["media"]
        .as_object()
        .ok_or("Missing actual media paths")?;
    let digests = receipt["media_sha256"]
        .as_object()
        .ok_or("Missing actual media identities")?;
    if media.len() != 4 || digests.len() != 4 {
        return Err("All four modalities are required".into());
    }
    let mut lengths = serde_json::Map::new();
    for kind in ["text", "image", "audio", "video"] {
        let bytes = checked(
            media[kind].as_str().ok_or("Invalid actual path")?,
            digests[kind].as_str().ok_or("Invalid actual SHA")?,
        )?;
        if kind == "text" {
            if bytes.len() > 4096 {
                return Err("Caption exceeds bound".into());
            }
            std::str::from_utf8(&bytes)?;
        } else if kind == "image" {
            if bytes.get(..8) != Some(b"\x89PNG\r\n\x1a\n")
                || bytes.get(12..16) != Some(b"IHDR")
                || bytes.get(16..20) != Some(&56_u32.to_be_bytes())
                || bytes.get(20..24) != Some(&28_u32.to_be_bytes())
            {
                return Err("Actual PNG profile mismatch".into());
            }
        } else if kind == "audio" {
            if bytes.get(..4) != Some(b"RIFF") || bytes.get(8..12) != Some(b"WAVE") {
                return Err("Actual audio is not PCM WAV".into());
            }
            let (mut offset, mut format, mut samples) = (12_usize, false, None);
            while offset + 8 <= bytes.len() {
                let count = little32(&bytes, offset + 4)? as usize;
                let data = offset + 8;
                if data + count > bytes.len() {
                    return Err("Truncated actual WAV chunk".into());
                }
                if bytes.get(offset..offset + 4) == Some(b"fmt ") {
                    if count < 16
                        || little16(&bytes, data)? != 1
                        || little16(&bytes, data + 2)? != 1
                        || little32(&bytes, data + 4)? != 8000
                        || little16(&bytes, data + 14)? != 16
                    {
                        return Err("Actual waveform format mismatch".into());
                    }
                    format = true;
                } else if bytes.get(offset..offset + 4) == Some(b"data") {
                    samples = Some(count / 2);
                }
                offset = data + count + (count % 2);
            }
            if !format || samples != Some(32000) {
                return Err("Actual waveform sample clock mismatch".into());
            }
        } else if bytes.get(4..8) != Some(b"ftyp") {
            return Err("Actual MP4 header mismatch".into());
        }
        lengths.insert(kind.to_string(), json!(bytes.len()));
    }
    let expected = json!({"duration_ns":4000000000_u64,"sample_rate":8000,"audio_samples":32000,
        "video_fps":5,"video_frames":20,"events":[
        {"slot":0,"audio_sample":0,"video_frame":0,"time_ns":0},
        {"slot":1,"audio_sample":16000,"video_frame":10,"time_ns":2000000000_u64}]});
    if receipt["clock"] != expected
        || receipt["codec_observation"]["target_supplied"] != false
        || receipt["codec_observation"]["lossless_roundtrip"] != true
    {
        return Err("Presentation clock or target-free codec observation mismatch".into());
    }
    Ok(
        json!({"native_file_hashes_checked":4,"actual_file_bytes":lengths,
        "wav_clock_parsed_natively":true,"PNG_header_parsed_natively":true,
        "MP4_decode_scope":"pinned host observer; native SHA-bound result","clock":expected}),
    )
}
