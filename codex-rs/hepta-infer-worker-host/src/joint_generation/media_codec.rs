//! Standard, directly readable codecs for the bounded v4 media tensors.
//! PPM: netpbm.sourceforge.net/doc/ppm.html; RIFF/WAVE: Microsoft RIFF spec.
//! Y4M: MJPEGtools yuv4mpeg(5), planar limited-range CCIR-601 Y', Cb, Cr.

use crate::codec::Result;

pub(crate) const MEDIA_PROFILE: &str = "ppm-wav16000-y4m4-v1";
const PPM_HEADER: &[u8] = b"P6\n16 16\n255\n";
const Y4M_HEADER: &[u8] = b"YUV4MPEG2 W16 H16 F4:1 Ip A1:1 C444\n";
const FRAME_HEADER: &[u8] = b"FRAME\n";

pub(crate) fn encode_chunk(modality: u8, start: u32, units: u32, raw: &[u8]) -> Result<Vec<u8>> {
    let mut result = Vec::new();
    match modality {
        0 => {
            if raw.len() != units as usize * 48 {
                return Err("PPM input row length".into());
            }
            if start == 0 {
                result.extend(PPM_HEADER);
            }
            result.extend(raw);
        }
        1 => {
            if raw.len() != units as usize * 2 {
                return Err("WAVE input sample length".into());
            }
            if start == 0 {
                result.extend(wave_header());
            }
            result.extend(raw);
        }
        2 => {
            if raw.len() != units as usize * 768 {
                return Err("Y4M input frame length".into());
            }
            if start == 0 {
                result.extend(Y4M_HEADER);
            }
            for frame in raw.chunks_exact(768) {
                result.extend(FRAME_HEADER);
                let mut planes = [0_u8; 768];
                for (pixel, rgb) in frame.chunks_exact(3).enumerate() {
                    let [r, g, b] = [
                        f64::from(rgb[0]) / 255.0,
                        f64::from(rgb[1]) / 255.0,
                        f64::from(rgb[2]) / 255.0,
                    ];
                    planes[pixel] = (16.0 + 65.481 * r + 128.553 * g + 24.966 * b)
                        .round_ties_even()
                        .clamp(16.0, 235.0) as u8;
                    planes[256 + pixel] = (128.0 - 37.797 * r - 74.203 * g + 112.0 * b)
                        .round_ties_even()
                        .clamp(16.0, 240.0) as u8;
                    planes[512 + pixel] = (128.0 + 112.0 * r - 93.786 * g - 18.214 * b)
                        .round_ties_even()
                        .clamp(16.0, 240.0) as u8;
                }
                result.extend(planes);
            }
        }
        _ => return Err("unknown standard media modality".into()),
    }
    Ok(result)
}

pub(crate) fn validate_chunk(modality: u8, start: u32, units: u32, payload: &[u8]) -> Result<()> {
    let wave = wave_header();
    let header = match modality {
        0 => PPM_HEADER,
        1 => &wave,
        2 => Y4M_HEADER,
        3 => {
            let text = std::str::from_utf8(payload).map_err(|_| "UTF-8 frame encoding")?;
            return if text.chars().count() == units as usize {
                Ok(())
            } else {
                Err("UTF-8 scalar count".into())
            };
        }
        _ => return Err("unknown standard media modality".into()),
    };
    let body = if start == 0 {
        payload
            .strip_prefix(header)
            .ok_or("standard media header mismatch")?
    } else {
        payload
    };
    let unit_bytes = [48, 2, 774][usize::from(modality)];
    if body.len() != units as usize * unit_bytes {
        return Err("standard media payload length".into());
    }
    if modality == 2
        && body
            .chunks_exact(774)
            .any(|frame| !frame.starts_with(FRAME_HEADER))
    {
        return Err("Y4M frame header mismatch".into());
    }
    Ok(())
}

fn wave_header() -> Vec<u8> {
    let mut header = b"RIFF".to_vec();
    header.extend((36_u32 + 2048).to_le_bytes());
    header.extend(b"WAVEfmt ");
    header.extend(16_u32.to_le_bytes());
    header.extend(1_u16.to_le_bytes()); // integer PCM
    header.extend(1_u16.to_le_bytes()); // mono
    header.extend(16_000_u32.to_le_bytes());
    header.extend(32_000_u32.to_le_bytes());
    header.extend(2_u16.to_le_bytes());
    header.extend(16_u16.to_le_bytes());
    header.extend(b"data");
    header.extend(2048_u32.to_le_bytes());
    header
}

#[cfg(test)]
#[path = "media_codec_tests.rs"]
mod tests;
