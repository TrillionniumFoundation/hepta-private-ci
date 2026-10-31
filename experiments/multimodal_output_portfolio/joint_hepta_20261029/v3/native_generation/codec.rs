//! Bounded, checksummed tensor packets and small native media encoders.
//! Linux research format v3; no pickle, dynamic libraries, or model subprocess.
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::Path;

pub type Result<T> = std::result::Result<T, String>;
#[derive(Clone, Debug, PartialEq)]
pub struct Tensor {
    pub shape: Vec<usize>,
    pub data: Vec<f64>,
}
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Packet {
    pub meta: BTreeMap<String, String>,
    pub tensors: BTreeMap<String, Tensor>,
}
const MAX_BYTES: usize = 64 * 1024 * 1024;

pub fn sha256(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut bytes = data.to_vec();
    let bits = (data.len() as u64) * 8;
    bytes.push(128);
    while bytes.len() % 64 != 56 {
        bytes.push(0);
    }
    bytes.extend(bits.to_be_bytes());
    let mut h = [
        0x6a09e667u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    for block in bytes.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (i, c) in block.chunks_exact(4).enumerate() {
            w[i] = u32::from_be_bytes(c.try_into().unwrap());
        }
        for i in 16..64 {
            let a = w[i - 15];
            let b = w[i - 2];
            w[i] = w[i - 16]
                .wrapping_add(a.rotate_right(7) ^ a.rotate_right(18) ^ (a >> 3))
                .wrapping_add(w[i - 7])
                .wrapping_add(b.rotate_right(17) ^ b.rotate_right(19) ^ (b >> 10));
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut z] = h;
        for i in 0..64 {
            let t = z
                .wrapping_add(e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25))
                .wrapping_add((e & f) ^ (!e & g))
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let u = (a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22))
                .wrapping_add((a & b) ^ (a & c) ^ (b & c));
            z = g;
            g = f;
            f = e;
            e = d.wrapping_add(t);
            d = c;
            c = b;
            b = a;
            a = t.wrapping_add(u);
        }
        for (x, y) in h.iter_mut().zip([a, b, c, d, e, f, g, z]) {
            *x = x.wrapping_add(y);
        }
    }
    h.iter().map(|v| format!("{v:08x}")).collect()
}
fn u32out(out: &mut Vec<u8>, v: usize) {
    out.extend((v as u32).to_le_bytes());
}
fn stringout(out: &mut Vec<u8>, v: &str) {
    u32out(out, v.len());
    out.extend(v.as_bytes());
}
impl Packet {
    pub fn vector(&mut self, name: &str, data: Vec<f64>) {
        self.tensors.insert(
            name.to_string(),
            Tensor {
                shape: vec![data.len()],
                data,
            },
        );
    }
    pub fn get(&self, name: &str) -> Result<&[f64]> {
        self.tensors
            .get(name)
            .map(|t| t.data.as_slice())
            .ok_or_else(|| format!("missing tensor {name}"))
    }
    pub fn text(&self, name: &str) -> Result<&str> {
        self.meta
            .get(name)
            .map(String::as_str)
            .ok_or_else(|| format!("missing metadata {name}"))
    }
    pub fn encode(&self) -> Result<Vec<u8>> {
        let mut out = b"HEPTAPK3".to_vec();
        u32out(&mut out, self.meta.len());
        for (k, v) in &self.meta {
            stringout(&mut out, k);
            stringout(&mut out, v);
        }
        u32out(&mut out, self.tensors.len());
        for (k, t) in &self.tensors {
            if t.data.iter().any(|x| !x.is_finite()) {
                return Err(format!("nonfinite {k}"));
            }
            stringout(&mut out, k);
            u32out(&mut out, t.shape.len());
            for d in &t.shape {
                u32out(&mut out, *d);
            }
            u32out(&mut out, t.data.len());
            for v in &t.data {
                out.extend(v.to_le_bytes());
            }
        }
        if out.len() > MAX_BYTES {
            return Err("packet too large".into());
        }
        let hash = sha256(&out);
        out.extend(hash.as_bytes());
        Ok(out)
    }
    pub fn read(path: &Path) -> Result<Self> {
        let meta = fs::symlink_metadata(path).map_err(|e| e.to_string())?;
        if !meta.file_type().is_file() || meta.len() > MAX_BYTES as u64 + 64 {
            return Err("invalid packet file".into());
        }
        let bytes = fs::read(path).map_err(|e| e.to_string())?;
        let decoded = Self::decode(&bytes)?;
        if decoded.encode()? != bytes {
            return Err("noncanonical packet".into());
        }
        Ok(decoded)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self> {
        if bytes.len() < 76 || bytes.len() > MAX_BYTES + 64 {
            return Err("invalid packet length".into());
        }
        let end = bytes.len() - 64;
        if sha256(&bytes[..end]).as_bytes() != &bytes[end..] {
            return Err("packet checksum mismatch".into());
        }
        let mut r = Reader {
            b: &bytes[..end],
            p: 0,
        };
        if r.take(8)? != b"HEPTAPK3" {
            return Err("unknown packet version".into());
        }
        let mut out = Self::default();
        let n = r.count(256)?;
        for _ in 0..n {
            let k = r.string()?;
            let v = r.string()?;
            if out.meta.insert(k, v).is_some() {
                return Err("duplicate metadata".into());
            }
        }
        let n = r.count(512)?;
        for _ in 0..n {
            let k = r.string()?;
            let nd = r.count(8)?;
            let mut shape = Vec::new();
            let mut product = 1usize;
            for _ in 0..nd {
                let d = r.count(4_000_000)?;
                product = product.checked_mul(d).ok_or("shape overflow")?;
                shape.push(d);
            }
            let size = r.count(4_000_000)?;
            if product != size {
                return Err("tensor shape mismatch".into());
            }
            let mut data = Vec::with_capacity(size);
            for _ in 0..size {
                let v = f64::from_le_bytes(r.take(8)?.try_into().unwrap());
                if !v.is_finite() {
                    return Err("nonfinite tensor".into());
                }
                data.push(v);
            }
            if out.tensors.insert(k, Tensor { shape, data }).is_some() {
                return Err("duplicate tensor".into());
            }
        }
        if r.p != end {
            return Err("packet trailing bytes".into());
        }
        Ok(out)
    }
}
struct Reader<'a> {
    b: &'a [u8],
    p: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self.p.checked_add(n).ok_or("size overflow")?;
        let v = self.b.get(self.p..end).ok_or("truncated packet")?;
        self.p = end;
        Ok(v)
    }
    fn count(&mut self, max: usize) -> Result<usize> {
        let n = u32::from_le_bytes(self.take(4)?.try_into().unwrap()) as usize;
        if n > max {
            Err("count exceeds bound".into())
        } else {
            Ok(n)
        }
    }
    fn string(&mut self) -> Result<String> {
        let n = self.count(8192)?;
        String::from_utf8(self.take(n)?.to_vec()).map_err(|e| e.to_string())
    }
}
pub fn immutable_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| e.to_string())?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|e| e.to_string())?;
    Ok(())
}
pub fn sync_dir(path: &Path) -> Result<()> {
    fs::File::open(path)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())
}

fn crc32(bytes: &[u8]) -> u32 {
    let mut c = 0xffff_ffffu32;
    for b in bytes {
        c ^= *b as u32;
        for _ in 0..8 {
            c = (c >> 1) ^ (0xedb8_8320 & 0u32.wrapping_sub(c & 1));
        }
    }
    !c
}
fn png_chunk(out: &mut Vec<u8>, tag: &[u8], bytes: &[u8]) {
    out.extend((bytes.len() as u32).to_be_bytes());
    let start = out.len();
    out.extend(tag);
    out.extend(bytes);
    out.extend(crc32(&out[start..]).to_be_bytes());
}
pub fn png(rgb: &[u8]) -> Result<Vec<u8>> {
    if rgb.len() != 768 {
        return Err("PNG requires 16x16 RGB".into());
    }
    let mut out = b"\x89PNG\r\n\x1a\n".to_vec();
    let mut ih = Vec::new();
    ih.extend(16u32.to_be_bytes());
    ih.extend(16u32.to_be_bytes());
    ih.extend([8, 2, 0, 0, 0]);
    png_chunk(&mut out, b"IHDR", &ih);
    let mut raw = Vec::new();
    for row in rgb.chunks_exact(48) {
        raw.push(0);
        raw.extend(row);
    }
    let mut z = vec![0x78, 0x01, 0x01];
    let n = raw.len() as u16;
    z.extend(n.to_le_bytes());
    z.extend((!n).to_le_bytes());
    z.extend(&raw);
    let (mut a, mut b) = (1u32, 0u32);
    for x in raw {
        a = (a + x as u32) % 65521;
        b = (b + a) % 65521;
    }
    z.extend(((b << 16) | a).to_be_bytes());
    png_chunk(&mut out, b"IDAT", &z);
    png_chunk(&mut out, b"IEND", &[]);
    Ok(out)
}
pub fn wav(pcm: &[u8], rate: u32) -> Result<Vec<u8>> {
    if pcm.len() != 2048 || rate == 0 || rate > 192000 {
        return Err("invalid PCM profile".into());
    }
    let mut out = b"RIFF".to_vec();
    out.extend((36 + pcm.len() as u32).to_le_bytes());
    out.extend(b"WAVEfmt ");
    out.extend(16u32.to_le_bytes());
    out.extend(1u16.to_le_bytes());
    out.extend(1u16.to_le_bytes());
    out.extend(rate.to_le_bytes());
    out.extend((rate * 2).to_le_bytes());
    out.extend(2u16.to_le_bytes());
    out.extend(16u16.to_le_bytes());
    out.extend(b"data");
    out.extend((pcm.len() as u32).to_le_bytes());
    out.extend(pcm);
    Ok(out)
}
/// Per-frame exact palette (at most 256 RGB pixels); fixed nine-bit LZW with
/// a clear before every pixel avoids changing decoder code width.
pub fn gif(rgb: &[u8], frame_ms: u16) -> Result<Vec<u8>> {
    if rgb.len() != 3072 || frame_ms == 0 || frame_ms % 10 != 0 {
        return Err("invalid GIF profile".into());
    }
    let mut out = b"GIF89a".to_vec();
    out.extend(16u16.to_le_bytes());
    out.extend(16u16.to_le_bytes());
    out.extend([0x70, 0, 0]);
    out.extend(b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00");
    for frame in rgb.chunks_exact(768) {
        out.extend([0x21, 0xf9, 4, 8]);
        out.extend((frame_ms / 10).to_le_bytes());
        out.extend([0, 0, 0x2c]);
        out.extend([0, 0, 0, 0]);
        out.extend(16u16.to_le_bytes());
        out.extend(16u16.to_le_bytes());
        out.push(0x87);
        out.extend(frame);
        out.push(8);
        let mut packed = Vec::new();
        let (mut buf, mut bits) = (0u32, 0u32);
        for code in (0..256u16).flat_map(|i| [256, i]).chain([257]) {
            buf |= (code as u32) << bits;
            bits += 9;
            while bits >= 8 {
                packed.push(buf as u8);
                buf >>= 8;
                bits -= 8;
            }
        }
        if bits > 0 {
            packed.push(buf as u8);
        }
        for block in packed.chunks(255) {
            out.push(block.len() as u8);
            out.extend(block);
        }
        out.push(0);
    }
    out.push(0x3b);
    Ok(out)
}
