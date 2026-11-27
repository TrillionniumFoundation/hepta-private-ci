//! Query-only consumption of the exact existing setup root grants.
use super::*;

struct ExistingRole {
    path: PathBuf,
    sid: Vec<u8>,
    access: u32,
}

fn existing_word(bytes: &[u8], offset: usize) -> Result<u16> {
    let value = bytes
        .get(offset..offset + 2)
        .ok_or_else(|| anyhow::anyhow!("short existing ACL word"))?;
    Ok(u16::from_le_bytes(value.try_into()?))
}

fn existing_dword(bytes: &[u8], offset: usize) -> Result<u32> {
    let value = bytes
        .get(offset..offset + 4)
        .ok_or_else(|| anyhow::anyhow!("short existing ACL field"))?;
    Ok(u32::from_le_bytes(value.try_into()?))
}

fn existing_sid(bytes: &[u8]) -> Result<&[u8]> {
    let header = bytes
        .get(..8)
        .ok_or_else(|| anyhow::anyhow!("short existing role SID"))?;
    ensure!(
        header[0] == 1 && header[1] <= 15,
        "invalid existing role SID"
    );
    bytes
        .get(..8 + 4 * usize::from(header[1]))
        .ok_or_else(|| anyhow::anyhow!("short existing SID body"))
}

fn require_existing_roles(
    bytes: &[u8],
    path: &Path,
    directory: bool,
    roles: &[ExistingRole],
) -> Result<()> {
    ensure!(
        bytes.len() <= 65_536
            && bytes.get(..2) == Some(&[1, 0])
            && existing_word(bytes, /*offset*/ 2)? & 0x8004 == 0x8004,
        "invalid existing root descriptor"
    );
    let owner_offset = existing_dword(bytes, /*offset*/ 4)? as usize;
    let acl_offset = existing_dword(bytes, /*offset*/ 16)? as usize;
    ensure!(
        owner_offset >= 20
            && owner_offset.is_multiple_of(4)
            && acl_offset >= 20
            && acl_offset.is_multiple_of(4)
    );
    let owner = existing_sid(
        bytes
            .get(owner_offset..)
            .ok_or_else(|| anyhow::anyhow!("missing root owner"))?,
    )?;
    ensure!(
        !roles.iter().any(|role| role.sid.as_slice() == owner),
        "filesystem role cannot own an observed root"
    );
    let acl = bytes
        .get(acl_offset..)
        .ok_or_else(|| anyhow::anyhow!("missing existing DACL"))?;
    let length = usize::from(existing_word(acl, /*offset*/ 2)?);
    let acl = acl
        .get(..length)
        .ok_or_else(|| anyhow::anyhow!("short existing DACL"))?;
    ensure!(
        acl.len() >= 8
            && matches!(acl[0], 2 | 4)
            && acl[1] == 0
            && existing_word(acl, /*offset*/ 6)? == 0
            && (owner_offset + owner.len() <= acl_offset || acl_offset + acl.len() <= owner_offset)
    );
    let count = existing_word(acl, /*offset*/ 4)?;
    ensure!(count <= 1024, "existing DACL exceeds ACE bound");
    let required = roles
        .iter()
        .filter(|role| role.path == path)
        .fold(0, |mask, role| mask | role.access);
    let flags = if directory { 3 } else { 0 };
    let mut present = vec![false; roles.len()];
    let mut cursor = 8;
    for _ in 0..count {
        let ace = acl
            .get(cursor..)
            .ok_or_else(|| anyhow::anyhow!("missing existing ACE"))?;
        let length = usize::from(existing_word(ace, /*offset*/ 2)?);
        ensure!(length >= 16 && length.is_multiple_of(4));
        let ace = ace
            .get(..length)
            .ok_or_else(|| anyhow::anyhow!("short existing ACE"))?;
        ensure!(
            matches!(ace[0], 0 | 1) && ace[1] & !0x1f == 0,
            "unsupported existing ACE"
        );
        let sid = existing_sid(&ace[8..])?;
        ensure!(sid.len() + 8 == length, "noncanonical existing ACE SID");
        let mask = existing_dword(ace, /*offset*/ 4)?;
        ensure!(
            ace[0] != 1 || ace[1] & 8 != 0 || mask & (required | 0xf000_0000) == 0,
            "conflicting effective root deny"
        );
        for (index, role) in roles.iter().enumerate() {
            if ace[0] == 0 && role.sid.as_slice() == sid {
                let maximum = if path.starts_with(&role.path) {
                    role.access
                } else {
                    0
                };
                ensure!(
                    mask & !maximum == 0,
                    "declared filesystem role exceeds this root's authority"
                );
                present[index] |= role.path == path && mask == role.access && ace[1] == flags;
            }
        }
        cursor += length;
    }
    ensure!(
        roles
            .iter()
            .enumerate()
            .all(|(index, role)| role.path != path || present[index]),
        "missing effective complete same-root role grant"
    );
    Ok(())
}

impl PreparedFilesystemAclContext {
    /// Consume existing setup grants using query handles only; never repair ACLs.
    /// This observes declared roots, not descendants, loaders or launch readiness.
    pub(crate) fn observe_existing(
        home: &Path,
        plan: &FilesystemCapabilityPlan,
        base: BorrowedHandle<'_>,
    ) -> Result<Self> {
        crate::validate_filesystem_capability_plan(home, plan)?;
        let base_version = token_version(base)?;
        let mut roles = Vec::new();
        for (path, sid, access) in plan
            .read_root_sids()
            .map(|(path, sid)| (path, sid, RX))
            .chain(plan.write_root_sids().map(|(path, sid)| (path, sid, WRITE)))
        {
            let canonical = dunce::canonicalize(path)?;
            let canonical = canonical
                .to_str()
                .ok_or_else(|| anyhow::anyhow!("non-Unicode existing root"))?
                .replace('\\', "/")
                .to_ascii_lowercase();
            ensure!(canonical == path, "noncanonical existing root declaration");
            let subject = LocalSid::from_string(sid)?;
            let length = unsafe { GetLengthSid(subject.as_ptr()) } as usize;
            ensure!((8..=68).contains(&length));
            // SAFETY: LocalSid owns this validated SID through the bounded copy.
            let sid = unsafe { std::slice::from_raw_parts(subject.as_ptr().cast::<u8>(), length) }
                .to_vec();
            ensure!(
                !roles.iter().any(|role: &ExistingRole| role.sid == sid),
                "filesystem roles overlap"
            );
            roles.push(ExistingRole {
                path: PathBuf::from(path),
                sid,
                access,
            });
        }
        ensure!(!roles.is_empty() && roles.len() <= 128);
        let read = crate::observe_filesystem_read_acl(home, plan)?;
        let mut roots = Vec::with_capacity(roles.len());
        for role in &roles {
            let file = read_acl_query::open(&role.path)?;
            let before = identity(&file)?;
            let bytes = descriptor(&file)?.1;
            require_existing_roles(&bytes, &role.path, file.metadata()?.is_dir(), &roles)?;
            require_access(&file, base, role.access)?;
            ensure!(
                identity(&file)? == before && descriptor(&file)?.1 == bytes,
                "existing root changed during readback"
            );
            roots.push(HeldRoot {
                path: role.path.clone(),
                file,
                identity: before,
                descriptor: bytes,
                access: role.access,
            });
        }
        let mut output = Self {
            home: home.to_owned(),
            plan: plan.clone(),
            read,
            roots,
            base_version,
            refused: false,
        };
        output.validate_for_token(base)?;
        Ok(output)
    }
}
