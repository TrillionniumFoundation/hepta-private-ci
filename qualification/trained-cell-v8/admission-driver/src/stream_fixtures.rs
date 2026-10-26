//! Sparse synthetic raw vectors still require every logical byte to be read and
//! hashed. References are independent constant-bias predictions, never a mock.
use super::*;
use sha2::Digest;
use sha2::Sha256;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

pub fn hash_file(path: &Path, offset: u64, length: u64) -> Result<Digest32> {
    let mut file = fs::File::open(path)?;
    file.seek(SeekFrom::Start(offset))?;
    let mut remaining = length;
    let mut hash = Sha256::new();
    let mut buffer = [0_u8; 65536];
    while remaining > 0 {
        let n = remaining.min(buffer.len() as u64) as usize;
        file.read_exact(&mut buffer[..n])?;
        hash.update(&buffer[..n]);
        remaining -= n as u64;
    }
    Ok(Digest32::from_array(hash.finalize().into()))
}

pub fn build(f: &Fixture, rows: [usize; 2]) -> Result<Digest32> {
    let old: Value = serde_json::from_slice(&read(&f.conversion)?)?;
    let mut header = if old["schema"] == "hepta.trained-cell-stream-parity.v8" {
        serde_json::from_slice::<Value>(&read(&f.parity.join("parity-header.json"))?)?
    } else {
        old
    };
    header["schema"] = json!("hepta.trained-cell-stream-header.v8");
    header["format"] = json!("float64-big-endian");
    header["input_width"] = json!(384);
    header["reference_width"] = json!(8);
    header["chunk_rows"] = json!(1024);
    header["labels_in_stream"] = json!(false);
    header["output_contract"] = json!("logits4-probabilities4-all-class-nll-argmax-first");
    header
        .as_object_mut()
        .unwrap()
        .remove("evaluated_terminal_checkpoints");
    let vectors = f.parity.join("vectors.bin");
    let total = (rows[0] + rows[1]) * 384 * 8;
    let mut file = fs::File::create(&vectors)?;
    file.set_len(total as u64)?;
    // A nonzero final feature forces the final logical row into the identity.
    file.seek(SeekFrom::End(-8))?;
    file.write_all(&0.03125_f64.to_be_bytes())?;
    file.sync_all()?;
    let mut tasks = Vec::new();
    let mut offset = 0;
    for (index, task) in report::TASKS.into_iter().enumerate() {
        let bytes = rows[index] * 384 * 8;
        tasks.push(json!({"task":task,"rows":rows[index],"offset_bytes":offset,
            "sha256":hash_file(&vectors,offset as u64,bytes as u64)?.to_string()}));
        offset += bytes;
    }
    header["tasks"] = json!(tasks);
    header["vectors_bytes"] = json!(total);
    header["vectors_sha256"] = json!(hash_file(&vectors, 0, total as u64)?.to_string());
    let expected = f.parity.join("expected.bin");
    let mut file = fs::File::create(&expected)?;
    let mut offset = 0;
    for (index, version) in header["versions"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .enumerate()
    {
        let bias = (index + 1) as f64 * 0.125;
        let mut row = Vec::new();
        for value in [bias, bias, bias, bias, 0.25, 0.25, 0.25, 0.25] {
            row.extend_from_slice(&value.to_be_bytes());
        }
        let block = row.repeat(1024);
        let mut cases = Vec::new();
        for head in version["heads"].as_array().unwrap() {
            let task = report::TASKS
                .iter()
                .position(|t| head["task"] == *t)
                .ok_or("task")?;
            let count = rows[task];
            let mut hash = Sha256::new();
            let mut remaining = count;
            while remaining > 0 {
                let n = remaining.min(1024);
                file.write_all(&block[..n * 64])?;
                hash.update(&block[..n * 64]);
                remaining -= n;
            }
            cases.push(json!({"cell_id":head["cell_id"],"task":head["task"],"rows":count,"offset_bytes":offset,
                "sha256":Digest32::from_array(hash.finalize().into()).to_string()}));
            offset += count * 64;
        }
        version["cases"] = json!(cases);
    }
    file.sync_all()?;
    header["expected_bytes"] = json!(offset);
    header["expected_sha256"] = json!(hash_file(&expected, 0, offset as u64)?.to_string());
    let digest = studies::write(&f.parity.join("parity-header.json"), &header)?;
    let conversion = json!({"schema":"hepta.trained-cell-stream-parity.v8","scope":header["scope"],
        "protocol_sha256":header["protocol_sha256"],"parity_header_sha256":digest.to_string(),
        "authority":"DENY_ALL","scientific_acceptance":false,"production_authority":false});
    studies::write(&f.conversion, &conversion)?;
    Ok(digest)
}
