//! Bounded RX-role readback; neither declaration nor descriptor grants launch authority.
use anyhow::Result;
use anyhow::ensure;

pub(crate) const RX: u32 = 0x0012_00a9;

#[derive(Clone, Copy)]
pub(crate) enum RootKind {
    File,
    Directory,
}

fn word(bytes: &[u8], offset: usize) -> Result<u16> {
    let value = bytes
        .get(offset..offset + 2)
        .ok_or_else(|| anyhow::anyhow!("short ACL word"))?;
    Ok(u16::from_le_bytes([value[0], value[1]]))
}

fn component(bytes: &[u8], offset: usize) -> Result<(usize, &[u8])> {
    let value = bytes
        .get(offset..offset + 4)
        .ok_or_else(|| anyhow::anyhow!("short descriptor offset"))?;
    let start = u32::from_le_bytes([value[0], value[1], value[2], value[3]]) as usize;
    ensure!(
        start >= 20 && start.is_multiple_of(4),
        "invalid descriptor component"
    );
    Ok((
        start,
        bytes
            .get(start..)
            .ok_or_else(|| anyhow::anyhow!("missing descriptor component"))?,
    ))
}

fn sid(bytes: &[u8]) -> Result<&[u8]> {
    let header = bytes
        .get(..8)
        .ok_or_else(|| anyhow::anyhow!("short role SID"))?;
    ensure!(header[0] == 1 && header[1] <= 15, "invalid role SID");
    bytes
        .get(..8 + 4 * usize::from(header[1]))
        .ok_or_else(|| anyhow::anyhow!("short role SID body"))
}

pub(crate) fn validate(
    bytes: &[u8],
    role: &[u8],
    other_roles: &[Vec<u8>],
    kind: RootKind,
) -> Result<()> {
    ensure!(
        bytes.len() <= 65_536 && bytes.get(..2) == Some(&[1, 0]),
        "invalid role descriptor size/revision"
    );
    ensure!(
        word(bytes, /*offset*/ 2)? & 0x8004 == 0x8004,
        "missing self-relative role DACL"
    );
    ensure!(
        bytes.get(8..16) == Some(&[0; 8]),
        "unexpected descriptor components"
    );
    ensure!(
        sid(role)? == role && other_roles.len() <= 64,
        "invalid role cohort"
    );
    let (owner_start, owner) = component(bytes, /*offset*/ 4)?;
    let owner = sid(owner)?;
    ensure!(
        owner != role && !other_roles.iter().any(|sid| sid.as_slice() == owner),
        "read role cannot own an object"
    );
    let (acl_start, acl) = component(bytes, /*offset*/ 16)?;
    let length = usize::from(word(acl, /*offset*/ 2)?);
    let acl = acl
        .get(..length)
        .ok_or_else(|| anyhow::anyhow!("truncated role ACL"))?;
    ensure!(
        acl.len() >= 8 && matches!(acl[0], 2 | 4) && acl[1] == 0 && word(acl, /*offset*/ 6)? == 0,
        "unsupported role ACL"
    );
    ensure!(
        owner_start + owner.len() <= acl_start || acl_start + acl.len() <= owner_start,
        "overlapping descriptor components"
    );
    let count = word(acl, /*offset*/ 4)?;
    ensure!(count <= 1024, "role ACL count bound exceeded");
    let expected_flags = match kind {
        RootKind::File => 0,
        RootKind::Directory => 3,
    };
    let mut cursor = 8;
    let mut complete = false;
    for _ in 0..count {
        let ace = acl
            .get(cursor..)
            .ok_or_else(|| anyhow::anyhow!("missing role ACE"))?;
        let length = usize::from(word(ace, /*offset*/ 2)?);
        ensure!(
            length >= 16 && length.is_multiple_of(4),
            "invalid role ACE extent"
        );
        let ace = ace
            .get(..length)
            .ok_or_else(|| anyhow::anyhow!("truncated role ACE"))?;
        ensure!(
            matches!(ace[0], 0 | 1) && ace[1] & !0x1f == 0,
            "unsupported role ACE form"
        );
        let trustee = sid(&ace[8..])?;
        ensure!(
            trustee.len() + 8 == length,
            "noncanonical role ACE SID extent"
        );
        let mask = u32::from_le_bytes([ace[4], ace[5], ace[6], ace[7]]);
        ensure!(
            ace[0] != 1 || ace[1] & 8 != 0 || mask & (RX | 0xf000_0000) == 0,
            "conflicting effective RX deny"
        );
        if ace[0] == 0 && trustee == role {
            // Check inherit-only ACEs too: a root's RX identity must never
            // acquire mutation authority over descendants through this grant.
            ensure!(
                mask & !RX == 0,
                "read role grants mutation or unknown access"
            );
            complete |= mask == RX && ace[1] == expected_flags;
        }
        ensure!(
            ace[0] != 0 || mask == 0 || !other_roles.iter().any(|sid| sid.as_slice() == trustee),
            "another declared root's role is granted here"
        );
        cursor += length;
    }
    ensure!(complete, "missing explicit complete same-root RX role");
    Ok(())
}

#[cfg(test)]
#[path = "read_role_descriptor_tests.rs"]
mod tests;
