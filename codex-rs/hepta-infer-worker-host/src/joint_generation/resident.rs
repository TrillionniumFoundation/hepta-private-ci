//! Framed resident transport. Only immutable model/public tensors survive a call.

use std::io::Read;
use std::io::Write;
use std::time::Instant;

use crate::codec::Result;
use crate::proposal::LoadedModel;
use crate::protocol::MAX_REQUEST_BYTES;
use crate::protocol::parse;

pub(crate) fn run_stdio() -> Result<()> {
    serve(std::io::stdin().lock(), std::io::stdout().lock())
}

pub(crate) fn serve(mut input: impl Read, mut output: impl Write) -> Result<()> {
    let mut loaded = None;
    while let Some(bytes) = read_frame(&mut input)? {
        let codec_start = Instant::now();
        let request = parse(&bytes)?;
        if loaded.is_some() {
            if !request.weights.is_empty() || !request.public.is_empty() {
                return Err("resident assets cannot be replaced".into());
            }
        } else {
            loaded = Some(LoadedModel::load(request.weights, request.public)?);
        }
        let response = loaded
            .as_ref()
            .ok_or("resident model missing")?
            .propose(request, codec_start)?
            .encode()?;
        let length = u32::try_from(response.len()).map_err(|_| "response length overflow")?;
        output
            .write_all(&length.to_le_bytes())
            .and_then(|()| output.write_all(&response))
            .and_then(|()| output.flush())
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn read_frame(input: &mut impl Read) -> Result<Option<Vec<u8>>> {
    let mut header = [0; 4];
    loop {
        match input.read(&mut header[..1]) {
            Ok(0) => return Ok(None),
            Ok(_) => break,
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.to_string()),
        }
    }
    input
        .read_exact(&mut header[1..])
        .map_err(|error| error.to_string())?;
    let length = u32::from_le_bytes(header) as usize;
    if length > MAX_REQUEST_BYTES || length == 0 {
        return Err("resident frame length exceeds bound".into());
    }
    let mut bytes = vec![0; length];
    input
        .read_exact(&mut bytes)
        .map_err(|error| error.to_string())?;
    Ok(Some(bytes))
}

#[cfg(test)]
#[path = "resident_tests.rs"]
mod tests;
