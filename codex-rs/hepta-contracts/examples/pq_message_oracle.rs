//! Reproducible message-level differential-test adapter. Disposable seeds only.
//! This is not a node endpoint, custody service, or alternate verifier.
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use serde_json::Value;
use serde_json::json;
use std::error::Error;
use std::io::Read;
use std::io::{self};
use zeroize::Zeroizing;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(DIGITS[usize::from(b >> 4)] as char);
        out.push(DIGITS[usize::from(b & 15)] as char);
    }
    out
}
fn unhex(value: &Value, name: &str) -> Result<Vec<u8>> {
    let text = value[name].as_str().ok_or("missing hex field")?;
    if !text.len().is_multiple_of(2) || text.len() > 140_000 {
        return Err("hex input length".into());
    }
    text.as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let digit = |b: u8| match b {
                b'0'..=b'9' => Ok(b - b'0'),
                b'a'..=b'f' => Ok(b - b'a' + 10),
                _ => Err("noncanonical hex"),
            };
            Ok((digit(pair[0])? << 4) | digit(pair[1])?)
        })
        .collect()
}
fn handle(value: &Value) -> Result<Value> {
    match value["mode"].as_str() {
        Some("sign") => {
            let number = value["test_seed"]
                .as_u64()
                .filter(|v| *v <= 255)
                .ok_or("disposable test seed")?;
            let seed = Zeroizing::new([number as u8; 32]);
            let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
            let key_id = ml_dsa_65_key_id_from_spki(&spki)?;
            let key = PqNativeSigningKey::from_owned_seed(seed, key_id)?;
            let message = unhex(value, "message")?;
            let signature = key.sign_exact_message(&message)?;
            Ok(json!({"spki":hex(&spki),"key_id":hex(&key_id),"signature":hex(&signature)}))
        }
        Some("verify") => {
            let spki = unhex(value, "spki")?;
            let key_id: [u8; 32] = unhex(value, "key_id")?
                .try_into()
                .map_err(|_| "key id length")?;
            let message = unhex(value, "message")?;
            let signature = unhex(value, "signature")?;
            let accepted = PqNativeVerifier::from_pinned_spki(&spki, key_id)
                .and_then(|v| v.verify_exact_message(&message, &signature).map(|_| ()))
                .is_ok();
            Ok(json!({"accepted":accepted}))
        }
        _ => Err("unknown operation".into()),
    }
}
fn main() -> Result<()> {
    let mut bytes = Vec::new();
    io::stdin().take(5_242_881).read_to_end(&mut bytes)?;
    if bytes.len() > 5_242_880 {
        return Err("input budget".into());
    }
    let input: Value = serde_json::from_slice(&bytes)?;
    let values = input
        .as_array()
        .filter(|v| v.len() <= 512)
        .ok_or("batch count")?;
    let results: Vec<_> = values.iter().map(handle).collect::<Result<_>>()?;
    println!("{}", serde_json::to_string(&results)?);
    Ok(())
}
