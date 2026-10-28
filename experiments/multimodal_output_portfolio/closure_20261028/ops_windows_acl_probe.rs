//! Observes unchanged production token and ACL behavior only on an owned fixture.
#![allow(dead_code)]

mod acl;
mod support;
mod token;
mod winutil;

use anyhow::Result;
use std::fs;
use std::path::Path;
use support::check;
use support::dump_acl;
use support::dump_token;
use support::open_matrix;
use support::operation;
use support::permission_denied;
use support::Impersonation;
use support::OwnedToken;
use token::LocalSid;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;

fn partial_deny(root: &Path) -> Result<()> {
    fs::create_dir(root)?;
    let capability = LocalSid::from_string("S-1-5-21-171-272-373-474")?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    unsafe {
        acl::ensure_allow_mask_aces(root, &[everyone.as_ptr()], FILE_ALL_ACCESS)?;
        acl::ensure_allow_write_aces(root, &[capability.as_ptr()])?;
    }
    let existing = root.join("existing.txt");
    fs::write(&existing, "original")?;
    support::seed_partial_deny(root, capability.as_ptr())?;
    dump_acl("partial.before.root", root)?;
    dump_acl("partial.before.file", &existing)?;
    let base = OwnedToken(unsafe { token::get_current_token_for_restriction()? });
    let restricted = OwnedToken(unsafe {
        token::create_workspace_write_token_with_caps_from(base.0, &[capability.as_ptr()])?
    });
    dump_token("partial.production", &restricted)?;
    {
        let _impersonation = Impersonation::enter(&restricted)?;
        check(
            "partial.before.overwrite_allowed",
            operation(
                "partial.before.overwrite",
                &fs::write(&existing, "before repair"),
            ),
        );
    }
    for (label, path, expected_rewrite) in [
        ("partial.repair.root", root, true),
        ("partial.repeat.root", root, false),
        ("partial.repair.file", existing.as_path(), true),
        ("partial.repeat.file", existing.as_path(), false),
    ] {
        let rewritten = unsafe { acl::add_deny_write_ace(path, capability.as_ptr())? };
        println!("REPAIR\t{label}\t{rewritten}");
        check(label, rewritten == expected_rewrite);
        dump_acl(label, path)?;
    }
    {
        let _impersonation = Impersonation::enter(&restricted)?;
        open_matrix("partial.after.file", &existing);
        open_matrix("partial.after.parent", root);
        let read = fs::read_to_string(&existing);
        operation("partial.after.read", &read);
        check(
            "partial.full_read_preserved",
            read.as_deref().ok() == Some("before repair"),
        );
        for (label, path) in [
            ("partial.after.overwrite", existing.clone()),
            ("partial.after.create", root.join("created.txt")),
        ] {
            let result = fs::write(path, "after repair");
            operation(label, &result);
            check(label, permission_denied(&result));
        }
    }
    check(
        "partial.final.content_preserved",
        fs::read_to_string(&existing).ok().as_deref() == Some("before repair"),
    );
    check(
        "partial.final.no_created_file",
        !root.join("created.txt").exists(),
    );
    Ok(())
}

fn broad_identity(root: &Path) -> Result<()> {
    fs::create_dir(root)?;
    let base = OwnedToken(unsafe { token::get_current_token_for_restriction()? });
    let cap_a = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let other = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    let mut logon = unsafe { token::get_logon_sid_bytes(base.0)? };
    let mut everyone = unsafe { token::world_sid()? };
    unsafe {
        acl::ensure_allow_mask_aces(
            root,
            &[logon.as_mut_ptr().cast(), everyone.as_mut_ptr().cast()],
            FILE_ALL_ACCESS,
        )?
    };
    let allowed = [root.join("workspace"), root.join("temp")];
    for (path, cap) in allowed.iter().zip([&cap_a, &cap_b]) {
        fs::create_dir(path)?;
        unsafe { acl::ensure_allow_write_aces(path, &[cap.as_ptr()])? };
        fs::write(path.join("delete.txt"), "inside")?;
        fs::create_dir(path.join("delete-dir"))?;
    }
    let outside = root.join("outside");
    fs::create_dir(&outside)?;
    unsafe { acl::ensure_allow_write_aces(&outside, &[other.as_ptr()])? };
    fs::write(outside.join("keep.txt"), "outside")?;
    fs::create_dir(outside.join("keep-dir"))?;
    let protected = allowed[0].join(".git");
    fs::create_dir(&protected)?;
    unsafe { acl::add_deny_write_ace(&protected, cap_a.as_ptr())? };
    for (label, path) in [
        ("broad.fixture", root.to_path_buf()),
        ("broad.allowed.parent", allowed[0].clone()),
        ("broad.allowed.file", allowed[0].join("delete.txt")),
        ("broad.outside.parent", outside.clone()),
        ("broad.outside.file", outside.join("keep.txt")),
        ("broad.protected.directory", protected.clone()),
    ] {
        dump_acl(label, &path)?;
    }
    let restricted = OwnedToken(unsafe {
        token::create_workspace_write_token_with_caps_from(
            base.0,
            &[cap_a.as_ptr(), cap_b.as_ptr()],
        )?
    });
    dump_token("broad.base", &base)?;
    dump_token("broad.production", &restricted)?;
    {
        let _impersonation = Impersonation::enter(&restricted)?;
        open_matrix("broad.outside.file", &outside.join("keep.txt"));
        open_matrix("broad.outside.parent", &outside);
        open_matrix("broad.allowed.file", &allowed[0].join("delete.txt"));
        open_matrix("broad.allowed.parent", &allowed[0]);
        open_matrix("broad.protected.directory", &protected);
        for (index, path) in allowed.iter().enumerate() {
            for (operation_name, result) in [
                ("create", fs::write(path.join("created.txt"), "allowed")),
                ("delete_file", fs::remove_file(path.join("delete.txt"))),
                ("delete_directory", fs::remove_dir(path.join("delete-dir"))),
            ] {
                let label = format!("broad.allowed.{index}.{operation_name}");
                check(&label, operation(&label, &result));
            }
        }
        let read = fs::read_to_string(outside.join("keep.txt"));
        operation("broad.outside.read", &read);
        check(
            "broad.full_read_preserved",
            read.as_deref().ok() == Some("outside"),
        );
        for (operation_name, result) in [
            (
                "overwrite",
                fs::write(outside.join("keep.txt"), "overwritten"),
            ),
            ("create", fs::write(outside.join("created.txt"), "outside")),
            ("delete_file", fs::remove_file(outside.join("keep.txt"))),
            ("delete_directory", fs::remove_dir(outside.join("keep-dir"))),
            ("delete_protected", fs::remove_dir(&protected)),
        ] {
            let label = format!("broad.refuse.{operation_name}");
            operation(&label, &result);
            check(&label, permission_denied(&result));
        }
    }
    check(
        "broad.final.outside_content_preserved",
        fs::read_to_string(outside.join("keep.txt")).ok().as_deref() == Some("outside"),
    );
    check(
        "broad.final.outside_directory_preserved",
        outside.join("keep-dir").is_dir(),
    );
    check(
        "broad.final.protected_directory_preserved",
        protected.is_dir(),
    );
    check(
        "broad.final.no_outside_created_file",
        !outside.join("created.txt").exists(),
    );
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    anyhow::ensure!(args.len() == 2, "expected one owned fixture path");
    let root = Path::new(&args[1]);
    anyhow::ensure!(
        root.is_absolute() && root.is_dir() && fs::read_dir(root)?.next().is_none(),
        "fixture must be a newly created empty directory"
    );
    anyhow::ensure!(
        !fs::symlink_metadata(root)?.file_type().is_symlink(),
        "fixture must not be a symlink"
    );
    partial_deny(&root.join("partial"))?;
    broad_identity(&root.join("broad"))?;
    println!("DONE\t2");
    Ok(())
}
