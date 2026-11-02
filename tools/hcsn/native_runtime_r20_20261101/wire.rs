//! Framed trusted-loopback protocol; checksums do not authenticate a peer.
use crate::common::{Result, ensure, read, seal, unseal};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::Path;
use std::time::Duration;
const MAX: usize = 65536;

pub fn send(stream: &mut TcpStream, text: &str) -> Result<()> {
    let text = seal(text);
    ensure(text.len() <= MAX, "wire capacity")?;
    stream.write_all(&(text.len() as u32).to_be_bytes())?;
    stream.write_all(text.as_bytes())?;
    Ok(())
}
pub fn receive(stream: &mut TcpStream) -> Result<String> {
    let mut length = [0; 4];
    stream.read_exact(&mut length)?;
    let length = u32::from_be_bytes(length) as usize;
    ensure(length > 0 && length <= MAX, "wire capacity")?;
    let mut data = vec![0; length];
    stream.read_exact(&mut data)?;
    let text = String::from_utf8(data)?;
    Ok(unseal(&text)?.into())
}
pub fn rpc(endpoint: &Path, request: &str) -> Result<String> {
    let address: SocketAddr = read(endpoint)?.trim_end().parse()?;
    ensure(
        address.is_ipv4() && address.ip().is_loopback(),
        "loopback endpoint only",
    )?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(1))?;
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    stream.set_write_timeout(Some(Duration::from_secs(1)))?;
    send(&mut stream, request)?;
    let response = receive(&mut stream)?;
    ensure(
        !response.starts_with("ERR\t"),
        &format!("provider rejected {response}"),
    )?;
    Ok(response)
}
