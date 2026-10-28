use anyhow::{ensure, Context, Result};
use serde_json::{json, Value};
use std::ffi::c_void;
use std::path::Path;
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, LocalFree};
use windows_sys::Win32::Security::Authorization::{
    ConvertSidToStringSidW, ConvertStringSecurityDescriptorToSecurityDescriptorW,
    GetNamedSecurityInfoW, SetEntriesInAclW, SetNamedSecurityInfoW, EXPLICIT_ACCESS_W,
    SE_FILE_OBJECT, TRUSTEE_IS_SID, TRUSTEE_IS_UNKNOWN, TRUSTEE_W,
};
use windows_sys::Win32::Security::{
    AccessCheck, DuplicateToken, GetAce, GetLengthSid, GetSecurityDescriptorLength,
    GetSecurityDescriptorSacl, GetTokenInformation, ImpersonateLoggedOnUser,
    MapGenericMask, RevertToSelf, SetTokenInformation, ACL, ACE_HEADER,
    DACL_SECURITY_INFORMATION, GENERIC_MAPPING, GROUP_SECURITY_INFORMATION,
    LABEL_SECURITY_INFORMATION, OWNER_SECURITY_INFORMATION, SID_AND_ATTRIBUTES,
    SecurityImpersonation, TOKEN_ACCESS_INFORMATION, TOKEN_MANDATORY_LABEL,
    TokenAccessInformation, TokenHasRestrictions, TokenIntegrityLevel,
    TokenMandatoryPolicy, TokenRestrictedSids,
};
use windows_sys::Win32::Storage::FileSystem::{
    DELETE, FILE_ALL_ACCESS, FILE_DELETE_CHILD, FILE_GENERIC_EXECUTE,
    FILE_GENERIC_READ, FILE_GENERIC_WRITE,
};

// The PowerShell entry verifies and copies the exact repository source files.
// These are the actual constructors and ACL mutators, not C# reimplementations.
mod acl;
mod token;
mod winutil;

struct OwnedToken(HANDLE);
impl Drop for OwnedToken {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0); }
    }
}

struct Impersonation;
impl Impersonation {
    fn enter(token: HANDLE) -> Result<Self> {
        ensure!(unsafe { ImpersonateLoggedOnUser(token) } != 0,
            "ImpersonateLoggedOnUser: {}", unsafe { GetLastError() });
        Ok(Self)
    }
}
impl Drop for Impersonation {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            // Never continue cleanup or diagnostics under a sandbox token.
            std::process::abort();
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

unsafe fn sid_string(sid: *mut c_void) -> Result<String> {
    let mut text = std::ptr::null_mut();
    ensure!(ConvertSidToStringSidW(sid, &mut text) != 0,
        "ConvertSidToStringSidW: {}", GetLastError());
    let mut len = 0;
    while *text.add(len) != 0 { len += 1; }
    let result = String::from_utf16_lossy(std::slice::from_raw_parts(text, len));
    LocalFree(text as isize);
    Ok(result)
}

unsafe fn token_bytes(handle: HANDLE, class: i32) -> Result<Vec<u8>> {
    let mut required = 0;
    GetTokenInformation(handle, class, std::ptr::null_mut(), 0, &mut required);
    ensure!(required != 0, "token class {class} size: {}", GetLastError());
    let mut bytes = vec![0u8; required as usize];
    ensure!(GetTokenInformation(handle, class, bytes.as_mut_ptr().cast(), required, &mut required) != 0,
        "token class {class} query: {}", GetLastError());
    Ok(bytes)
}

unsafe fn token_report(handle: HANDLE) -> Result<Value> {
    let groups = token_bytes(handle, TokenRestrictedSids)?;
    let count = std::ptr::read_unaligned(groups.as_ptr().cast::<u32>()) as usize;
    let align = std::mem::align_of::<SID_AND_ATTRIBUTES>();
    let offset = (std::mem::size_of::<u32>() + align - 1) & !(align - 1);
    let mut sids = Vec::new();
    for i in 0..count {
        let entry = std::ptr::read_unaligned(groups.as_ptr().add(offset + i * std::mem::size_of::<SID_AND_ATTRIBUTES>()).cast::<SID_AND_ATTRIBUTES>());
        sids.push(json!({"sid": sid_string(entry.Sid)?, "attributes": entry.Attributes}));
    }
    let label_bytes = token_bytes(handle, TokenIntegrityLevel)?;
    let label = std::ptr::read_unaligned(label_bytes.as_ptr().cast::<TOKEN_MANDATORY_LABEL>());
    let policy = token_bytes(handle, TokenMandatoryPolicy)?;
    let restricted = token_bytes(handle, TokenHasRestrictions)?;
    let access = token_bytes(handle, TokenAccessInformation)?;
    let access = std::ptr::read_unaligned(access.as_ptr().cast::<TOKEN_ACCESS_INFORMATION>());
    Ok(json!({
        "constructor_flags": "DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED = 0x0d",
        "access_information_flags": access.Flags,
        "restricted_sids": sids,
        "integrity_sid": sid_string(label.Label.Sid)?,
        "mandatory_policy": u32::from_ne_bytes(policy[..4].try_into()?),
        "has_restrictions": u32::from_ne_bytes(restricted[..4].try_into()?),
    }))
}

unsafe fn acl_report(acl: *mut ACL) -> Result<Value> {
    if acl.is_null() { return Ok(Value::Null); }
    let header = std::ptr::read_unaligned(acl);
    let mut entries = Vec::new();
    for i in 0..header.AceCount {
        let mut entry: *mut c_void = std::ptr::null_mut();
        ensure!(GetAce(acl, u32::from(i), &mut entry) != 0, "GetAce: {}", GetLastError());
        let h = std::ptr::read_unaligned(entry.cast::<ACE_HEADER>());
        let bytes = std::slice::from_raw_parts(entry.cast::<u8>(), usize::from(h.AceSize));
        let mask = if bytes.len() >= 8 { Some(u32::from_ne_bytes(bytes[4..8].try_into()?)) } else { None };
        let sid = if matches!(h.AceType, 0 | 1 | 17) && bytes.len() >= 12 {
            Some(sid_string(entry.cast::<u8>().add(8).cast())?)
        } else { None };
        entries.push(json!({"index":i,"type":h.AceType,"flags":h.AceFlags,"mask":mask,"sid":sid,"raw_hex":hex(bytes)}));
    }
    Ok(json!({"revision":header.AclRevision,"bytes":header.AclSize,"entries":entries,
        "raw_hex":hex(std::slice::from_raw_parts(acl.cast::<u8>(),usize::from(header.AclSize)))}))
}

unsafe fn security_report(path: &Path, token: Option<HANDLE>) -> Result<Value> {
    let mut descriptor: *mut c_void = std::ptr::null_mut();
    let mut dacl = std::ptr::null_mut();
    let mut sacl = std::ptr::null_mut();
    let code = GetNamedSecurityInfoW(winutil::to_wide(path).as_ptr(), SE_FILE_OBJECT,
        OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION | LABEL_SECURITY_INFORMATION,
        std::ptr::null_mut(), std::ptr::null_mut(), &mut dacl, &mut sacl, &mut descriptor);
    ensure!(code == 0, "GetNamedSecurityInfoW {}: {code}", path.display());
    let result = (|| -> Result<Value> {
        let mut checks = Vec::new();
        if let Some(token) = token {
            let mut duplicate = 0;
            ensure!(DuplicateToken(token, SecurityImpersonation, &mut duplicate) != 0,
                "DuplicateToken: {}", GetLastError());
            let duplicate = OwnedToken(duplicate);
            for (name, mut desired) in [("DELETE", DELETE), ("FILE_DELETE_CHILD", FILE_DELETE_CHILD),
                ("GENERIC_WRITE", 0x40000000u32), ("GENERIC_READ", 0x80000000u32)] {
                let mut mapping = GENERIC_MAPPING {GenericRead:FILE_GENERIC_READ, GenericWrite:FILE_GENERIC_WRITE,
                    GenericExecute:FILE_GENERIC_EXECUTE, GenericAll:FILE_ALL_ACCESS};
                MapGenericMask(&mut desired, &mapping);
                let mut privilege_bytes = vec![0u64; 512];
                let mut privilege_len = (privilege_bytes.len() * 8) as u32;
                let mut granted = 0;
                let mut allowed = 0;
                let succeeded = AccessCheck(descriptor, duplicate.0, desired, &mut mapping,
                    privilege_bytes.as_mut_ptr().cast(), &mut privilege_len, &mut granted, &mut allowed);
                let error = if succeeded == 0 { GetLastError() } else { 0 };
                checks.push(json!({"right":name,"desired_mask":desired,"api_succeeded":succeeded!=0,
                    "allowed":allowed!=0,"granted_mask":granted,"win32_error":error,"privilege_set_bytes":privilege_len}));
            }
        }
        Ok(json!({"path":path,"dacl":acl_report(dacl)?,"label_sacl":acl_report(sacl)?,
            "security_descriptor_hex":hex(std::slice::from_raw_parts(descriptor.cast::<u8>(), GetSecurityDescriptorLength(descriptor) as usize)),
            "access_checks":checks}))
    })();
    LocalFree(descriptor as isize);
    result
}

unsafe fn set_entry(path: &Path, sid: *mut c_void, mask: u32, mode: i32) -> Result<()> {
    let (old, descriptor) = acl::fetch_dacl_handle(path)?;
    let entry = EXPLICIT_ACCESS_W {grfAccessPermissions:mask,grfAccessMode:mode,grfInheritance:3,
        Trustee:TRUSTEE_W {pMultipleTrustee:std::ptr::null_mut(),MultipleTrusteeOperation:0,
            TrusteeForm:TRUSTEE_IS_SID,TrusteeType:TRUSTEE_IS_UNKNOWN,ptstrName:sid.cast()}};
    let mut updated = std::ptr::null_mut();
    let mut code = SetEntriesInAclW(1, &entry, old, &mut updated);
    if code == 0 {
        code = SetNamedSecurityInfoW(winutil::to_wide(path).as_ptr() as *mut u16, SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION, std::ptr::null_mut(), std::ptr::null_mut(), updated, std::ptr::null_mut());
    }
    if !updated.is_null() { LocalFree(updated as isize); }
    LocalFree(descriptor as isize);
    ensure!(code == 0, "diagnostic SetEntries/SetNamed {}: {code}",path.display());
    Ok(())
}

// Candidate-only diagnostic; not a production fix or part of the bound source.
unsafe fn lower_token_to_low(handle: HANDLE) -> Result<()> {
    let sid = token::LocalSid::from_string("S-1-16-4096")?;
    let label = TOKEN_MANDATORY_LABEL {Label:SID_AND_ATTRIBUTES {Sid:sid.as_ptr(),Attributes:0x20}};
    ensure!(SetTokenInformation(handle,TokenIntegrityLevel,(&label as *const TOKEN_MANDATORY_LABEL).cast(),
        std::mem::size_of::<TOKEN_MANDATORY_LABEL>() as u32 + GetLengthSid(sid.as_ptr())) != 0,
        "SetTokenInformation low: {}",GetLastError());
    Ok(())
}

unsafe fn label_low(path: &Path) -> Result<()> {
    let mut descriptor = std::ptr::null_mut();
    ensure!(ConvertStringSecurityDescriptorToSecurityDescriptorW(winutil::to_wide("S:(ML;OICI;NW;;;LW)").as_ptr(),
        1,&mut descriptor,std::ptr::null_mut()) != 0,"low label SDDL: {}",GetLastError());
    let result = (|| -> Result<()> {
        let mut present = 0;
        let mut defaulted = 0;
        let mut sacl = std::ptr::null_mut();
        ensure!(GetSecurityDescriptorSacl(descriptor,&mut present,&mut sacl,&mut defaulted)!=0 && present!=0,
            "GetSecurityDescriptorSacl: {}",GetLastError());
        let code=SetNamedSecurityInfoW(winutil::to_wide(path).as_ptr() as *mut u16,SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION,std::ptr::null_mut(),std::ptr::null_mut(),std::ptr::null_mut(),sacl);
        ensure!(code==0,"label Low {}: {code}",path.display());
        Ok(())
    })();
    LocalFree(descriptor as isize);
    result
}

fn io_outcome<T>(result: std::io::Result<T>) -> Value {
    match result {
        Ok(_) => json!({"ok":true}),
        Err(error) => json!({"ok":false,"kind":format!("{:?}",error.kind()),"os_error":error.raw_os_error(),"message":error.to_string()}),
    }
}

fn effects(path: &Path) -> Value {
    json!({"overwrite_contents":std::fs::read_to_string(path.join("overwrite.txt")).ok(),
        "created_exists":path.join("created.txt").exists(),
        "delete_file_exists":path.join("delete.txt").exists(),
        "delete_directory_exists":path.join("delete-dir").is_dir(),
        "rename_source_exists":path.join("rename.txt").exists(),
        "rename_destination_exists":path.join("renamed.txt").exists()})
}

fn run_case(root: &Path, use_low_candidate: bool) -> Result<Value> {
    std::fs::create_dir(root)?;
    let base = OwnedToken(unsafe { token::get_current_token_for_restriction()? });
    let cap_a=token::LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b=token::LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let stale_cap=token::LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    let everyone=token::LocalSid::from_string("S-1-1-0")?;
    let mut logon=unsafe { token::get_logon_sid_bytes(base.0)? };
    unsafe { acl::ensure_allow_mask_aces(root,&[everyone.as_ptr(),logon.as_mut_ptr().cast()],FILE_ALL_ACCESS)?; }
    let entries=[("workspace",Some(cap_a.as_ptr())),("temp",Some(cap_b.as_ptr())),
        ("stale-capability",Some(stale_cap.as_ptr())),("outside-medium",None),("outside-preexisting-low",None)];
    for (name,cap) in entries {
        let path=root.join(name);std::fs::create_dir(&path)?;
        if let Some(cap)=cap { unsafe { acl::ensure_allow_write_aces(&path,&[cap])?; } }
        if use_low_candidate && cap.is_some() {
            unsafe { set_entry(&path,everyone.as_ptr(),FILE_DELETE_CHILD,3)?;label_low(&path)?; }
        }
        if name=="outside-preexisting-low" { unsafe { label_low(&path)?; } }
        for file in ["overwrite.txt","delete.txt","rename.txt"] {std::fs::write(path.join(file),"original")?;}
        std::fs::create_dir(path.join("delete-dir"))?;
    }
    let protected=root.join("workspace/protected");std::fs::create_dir(&protected)?;
    std::fs::write(protected.join("keep.txt"),"protected")?;
    unsafe { acl::add_deny_write_ace(&protected,cap_a.as_ptr())?; }
    let restricted=OwnedToken(unsafe {token::create_workspace_write_token_with_caps_from(base.0,&[cap_a.as_ptr(),cap_b.as_ptr()])?});
    if use_low_candidate { unsafe { lower_token_to_low(restricted.0)?; } }
    let mut paths=Vec::new();
    for (name,_) in entries {
        let path=root.join(name);
        let before=effects(&path);
        let directory_security=unsafe {security_report(&path,Some(restricted.0))?};
        let file_security=unsafe {security_report(&path.join("delete.txt"),Some(restricted.0))?};
        let operations={
            let _guard=Impersonation::enter(restricted.0)?;
            json!({"read":io_outcome(std::fs::read(path.join("overwrite.txt"))),
                "overwrite":io_outcome(std::fs::write(path.join("overwrite.txt"),"modified")),
                "create":io_outcome(std::fs::write(path.join("created.txt"),"created")),
                "delete_file":io_outcome(std::fs::remove_file(path.join("delete.txt"))),
                "delete_directory":io_outcome(std::fs::remove_dir(path.join("delete-dir"))),
                "rename":io_outcome(std::fs::rename(path.join("rename.txt"),path.join("renamed.txt")))})
        };
        paths.push(json!({"case":name,"before":before,"directory_security":directory_security,
            "file_security":file_security,"operations":operations,"after":effects(&path)}));
    }
    let protected_security=unsafe{security_report(&protected,Some(restricted.0))?};
    let protected_delete={let _guard=Impersonation::enter(restricted.0)?;io_outcome(std::fs::remove_file(protected.join("keep.txt")))};
    Ok(json!({"case":if use_low_candidate{"candidate_low_and_parent_deny"}else{"exact_repository_token"},
        "token":unsafe{token_report(restricted.0)?},"paths":paths,"protected_security":protected_security,
        "protected_file_delete":protected_delete,"protected_file_exists":protected.join("keep.txt").exists()}))
}

fn run_repair(root: &Path) -> Result<Value> {
    std::fs::create_dir(root)?;
    let cap=token::LocalSid::from_string("S-1-5-21-171-272-373-474")?;
    let everyone=token::LocalSid::from_string("S-1-1-0")?;
    unsafe {acl::ensure_allow_mask_aces(root,&[everyone.as_ptr()],FILE_ALL_ACCESS)?;acl::ensure_allow_write_aces(root,&[cap.as_ptr()])?;}
    let file=root.join("existing.txt");std::fs::write(&file,"original")?;
    unsafe{set_entry(root,cap.as_ptr(),DELETE,3)?;}
    let mut stages=vec![json!({"stage":"seed_partial_DELETE","directory":unsafe{security_report(root,None)?},"file":unsafe{security_report(&file,None)?}})];
    for (name,path) in [("repair_directory",root),("repeat_directory",root),("repair_file",file.as_path()),("repeat_file",file.as_path())] {
        let repaired=unsafe{acl::add_deny_write_ace(path,cap.as_ptr())?};
        stages.push(json!({"stage":name,"reported_changed":repaired,"security":unsafe{security_report(path,None)?}}));
    }
    Ok(json!({"stages":stages}))
}

fn run() -> Result<()> {
    let output=std::env::args_os().nth(1).context("output JSON path required")?;
    let fixture=tempfile::Builder::new().prefix("hepta-windows-token-diagnostic-").tempdir()?;
    let exact=run_case(&fixture.path().join("exact"),false);
    let candidate=run_case(&fixture.path().join("candidate"),true);
    let repair=run_repair(&fixture.path().join("repair"));
    let mut complete=true;
    let mut result=|value:Result<Value>| match value {Ok(value)=>value,Err(error)=>{complete=false;json!({"diagnostic_error":format!("{error:#}")})}};
    let exact=result(exact);let candidate=result(candidate);let repair=result(repair);
    let mut report=json!({"schema":"hepta.windows-token-diagnostic.v1","evidence_complete":complete,
        "meaning":"Diagnostic completion is not a security qualification. Physical side effects are authoritative; AccessCheck is supporting evidence.",
        "source_identity":include_str!("source-identity.json"),"fixture_root":fixture.path(),
        "exact_repository":exact,"candidate_low_integrity":candidate,"acl_repair":repair});
    // Only the fresh TempDir is removed. Never accept caller-provided fixture roots.
    let cleanup=fixture.close();
    report["cleanup"]=match &cleanup {Ok(())=>json!({"ok":true}),Err(error)=>json!({"ok":false,"error":error.to_string()})};
    std::fs::write(output,serde_json::to_vec_pretty(&report)?)?;
    cleanup.context("remove owned diagnostic fixture")?;
    ensure!(complete,"one or more diagnostic probes failed; see raw JSON");
    Ok(())
}

fn main() {
    if let Err(error)=run(){eprintln!("{error:#}");std::process::exit(1);}
}
