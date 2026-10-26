//! Actual negative native calls made by Root, which holds no manage/history slot.
use super::boot::Boot;
use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;

pub(super) fn statuses(boot: &Boot, file: &File) -> io::Result<(u16, u16)> {
    let mut install = [0_u8; 32];
    install[..8].copy_from_slice(&1_u64.to_le_bytes());
    install[8..16].copy_from_slice(&100_000_000_u64.to_le_bytes());
    install[16..24].copy_from_slice(&25_000_000_u64.to_le_bytes());
    let manage = denial(file, boot, 3, 2, &install)?;
    let mut history = [0_u8; 40];
    history[..16].copy_from_slice(&boot.page[96..112]);
    history[16..32].copy_from_slice(&boot.page[112..128]);
    history[32..40].copy_from_slice(&1_u64.to_le_bytes());
    let history = denial(file, boot, 4, 3, &history)?;
    if manage != 2 || history != 2 {
        return Err(io::Error::other(
            "Root acquired native management/history authority",
        ));
    }
    Ok((manage, history))
}

fn denial(file: &File, boot: &Boot, opcode: u16, slot: u64, payload: &[u8]) -> io::Result<u16> {
    let mut input = [0_u8; 104];
    input[..4].copy_from_slice(b"HOS2");
    input[4..6].copy_from_slice(&2_u16.to_le_bytes());
    input[8..10].copy_from_slice(&opcode.to_le_bytes());
    input[12..16].copy_from_slice(&64_u32.to_le_bytes());
    input[16..20].copy_from_slice(&(payload.len() as u32).to_le_bytes());
    input[24..32].copy_from_slice(&1_u64.to_le_bytes());
    input[40..48].copy_from_slice(&slot.to_le_bytes());
    input[48..56].copy_from_slice(&1_u64.to_le_bytes());
    input[64..64 + payload.len()].copy_from_slice(payload);
    let mut output = [0_u8; 128];
    let mut descriptor = [0_u8; 32];
    descriptor[..8].copy_from_slice(&(input.as_ptr() as u64).to_le_bytes());
    descriptor[8..16].copy_from_slice(&(output.as_mut_ptr() as u64).to_le_bytes());
    descriptor[16..20].copy_from_slice(&((64 + payload.len()) as u32).to_le_bytes());
    descriptor[20..24].copy_from_slice(&128_u32.to_le_bytes());
    // SAFETY: fixed original HOS2 ioctl receives bounded live borrowed buffers.
    // This deliberately unauthorised call cannot obtain a slot or create a D.
    if unsafe {
        libc::ioctl(
            file.as_raw_fd(),
            0xc020_4802 as libc::c_ulong,
            descriptor.as_mut_ptr(),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    if &output[..4] != b"HOSR"
        || output[4..8] != [2, 0, 0, 0]
        || output[8..10] != opcode.to_le_bytes()
        || output[12..16] != 64_u32.to_le_bytes()
        || output[16..24] != [0; 8]
        || output[24..40] != input[24..40]
        || output[40..56] != boot.page[96..112]
        || output[56..64] != [0; 8]
    {
        return Err(io::Error::other("uncorrelated Root denial response"));
    }
    Ok(u16::from_le_bytes(output[10..12].try_into().unwrap()))
}
