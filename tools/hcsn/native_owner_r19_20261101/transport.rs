//! Durable request allocation and bounded, unauthenticated local IPv4 relay.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::Path;
use std::time::{Duration, Instant};

use crate::common::{Result, atomic, ensure, fault, lock, read, seal, unseal};

const MAX_WIRE: usize = 65_536;

fn hex(text: &str) -> String {
    text.as_bytes().iter().map(|b| format!("{b:02x}")).collect()
}

fn unhex(text: &str) -> Result<String> {
    ensure(text.len() % 2 == 0 && text.is_ascii(), "invalid hex")?;
    let bytes: std::result::Result<Vec<_>, _> = (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16))
        .collect();
    Ok(String::from_utf8(bytes?)?)
}

fn allocate(mailbox: &Path) -> Result<(String, std::fs::File)> {
    let allocation_lock = lock(&mailbox.join("client-sequence.lock"))?;
    let sequence = mailbox.join("client-sequence");
    let prior: u64 = if sequence.exists() {
        unseal(&read(&sequence)?)?.trim_end().parse()?
    } else {
        0
    };
    let next = prior.checked_add(1).ok_or("request sequence exhausted")?;
    // Persist allocation before publishing the request. Process death may leave
    // gaps, but PID reuse and fresh process-local counters cannot reuse an ID.
    atomic(&sequence, &seal(&format!("{next}\n")))?;
    let id = format!("0-{next:020}");
    let request_path = mailbox.join(format!("{id}.req"));
    let response_path = mailbox.join(format!("{id}.resp"));
    ensure(
        !request_path.exists() && !response_path.exists(),
        "request allocation conflict",
    )?;
    Ok((id, allocation_lock))
}

pub fn allocate_for_fault(mailbox: &Path, stop: &str, marker: &Path) -> Result<()> {
    let (id, _allocation_lock) = allocate(mailbox)?;
    fault("allocated_before_publish", stop, marker)?;
    println!("ALLOCATED\t{id}");
    Ok(())
}

fn mailbox_rpc(mailbox: &Path, request: &str) -> Result<String> {
    ensure(request.len() <= MAX_WIRE, "request capacity")?;
    let (id, allocation_lock) = allocate(mailbox)?;
    let request_path = mailbox.join(format!("{id}.req"));
    let response_path = mailbox.join(format!("{id}.resp"));
    atomic(
        &request_path,
        &seal(&format!("REQ\t{id}\t{}\n", hex(request))),
    )?;
    drop(allocation_lock);
    let deadline = Instant::now() + Duration::from_secs(3);
    while !response_path.exists() {
        ensure(Instant::now() < deadline, "provider response timeout")?;
        std::thread::sleep(Duration::from_millis(1));
    }
    let text = read(&response_path)?;
    let fields: Vec<_> = unseal(&text)?.trim_end().split('\t').collect();
    ensure(
        fields.len() == 3 && fields[0] == "RESP" && fields[1] == id,
        "response envelope",
    )?;
    let response = unhex(fields[2])?;
    std::fs::remove_file(response_path)?;
    Ok(response)
}

fn receive(stream: &mut TcpStream) -> Result<String> {
    let mut length = [0; 4];
    stream.read_exact(&mut length)?;
    let length = u32::from_be_bytes(length) as usize;
    ensure(length > 0 && length <= MAX_WIRE, "wire capacity")?;
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes)?;
    Ok(String::from_utf8(bytes)?)
}

fn send(stream: &mut TcpStream, text: &str) -> Result<()> {
    ensure(!text.is_empty() && text.len() <= MAX_WIRE, "wire capacity")?;
    stream.write_all(&(text.len() as u32).to_be_bytes())?;
    stream.write_all(text.as_bytes())?;
    Ok(())
}

pub fn rpc(endpoint: &Path, request: &str) -> Result<String> {
    let response = if endpoint.is_file() {
        let address: SocketAddr = read(endpoint)?.trim_end().parse()?;
        ensure(
            address.is_ipv4() && address.ip().is_loopback(),
            "loopback only",
        )?;
        let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(1))?;
        stream.set_read_timeout(Some(Duration::from_secs(4)))?;
        stream.set_write_timeout(Some(Duration::from_secs(1)))?;
        send(&mut stream, request)?;
        receive(&mut stream)?
    } else {
        mailbox_rpc(endpoint, request)?
    };
    ensure(
        !response.starts_with("ERR") && !response.is_empty(),
        &format!("provider rejected: {response}"),
    )?;
    Ok(response)
}

pub fn serve(endpoint: &Path, mailbox: &Path, stop: &str, marker: &Path) -> Result<()> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    atomic(endpoint, &format!("{}\n", listener.local_addr()?))?;
    for connection in listener.incoming() {
        let mut stream = connection?;
        stream.set_read_timeout(Some(Duration::from_millis(500)))?;
        stream.set_write_timeout(Some(Duration::from_millis(500)))?;
        let request = match receive(&mut stream) {
            Ok(request) => request,
            Err(error) => {
                eprintln!("rejected frame: {error}");
                continue;
            }
        };
        // Storage/allocation uncertainty terminates the relay before success.
        let response = mailbox_rpc(mailbox, &request)?;
        if request.starts_with("CALL\t") && response.starts_with("EFFECT\t") {
            fault("relay_after_effect", stop, marker)?;
        }
        // A disconnected peer does not undo a committed provider effect.
        if let Err(error) = send(&mut stream, &response) {
            eprintln!("reply delivery failed: {error}");
        }
    }
    Ok(())
}
