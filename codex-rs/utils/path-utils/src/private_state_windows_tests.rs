    use super::*;
    use windows_sys::Win32::Security::ACL_REVISION;
    use windows_sys::Win32::Security::AddAccessAllowedAceEx;
    use windows_sys::Win32::Security::CreateWellKnownSid;
    use windows_sys::Win32::Security::GetLengthSid;
    use windows_sys::Win32::Security::InitializeAcl;
    use windows_sys::Win32::Security::WinWorldSid;
    use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;

    fn world_sid() -> Vec<u32> {
        let mut length = 0;
        unsafe {
            CreateWellKnownSid(WinWorldSid, ptr::null_mut(), ptr::null_mut(), &mut length);
        }
        assert!(length > 0);
        let mut sid = vec![0_u32; (length as usize).div_ceil(std::mem::size_of::<u32>())];
        assert_ne!(
            unsafe {
                CreateWellKnownSid(
                    WinWorldSid,
                    ptr::null_mut(),
                    sid.as_mut_ptr().cast(),
                    &mut length,
                )
            },
            0
        );
        sid
    }

    #[test]
    fn public_read_access_is_not_private() {
        let current_user = CurrentUser::read().expect("current user");
        let world = world_sid();
        let current_user_length = unsafe { GetLengthSid(current_user.sid()) } as usize;
        let world_length = unsafe { GetLengthSid(world.as_ptr().cast_mut().cast()) } as usize;
        let acl_bytes = std::mem::size_of::<ACL>()
            + 2 * (std::mem::size_of::<ACCESS_ALLOWED_ACE>() - std::mem::size_of::<u32>())
            + current_user_length
            + world_length;
        let mut storage = vec![0_u32; acl_bytes.div_ceil(std::mem::size_of::<u32>())];
        let dacl = storage.as_mut_ptr().cast::<ACL>();
        assert_ne!(
            unsafe { InitializeAcl(dacl, acl_bytes as u32, ACL_REVISION) },
            0
        );
        assert_ne!(
            unsafe {
                AddAccessAllowedAceEx(dacl, ACL_REVISION, 0, FILE_ALL_ACCESS, current_user.sid())
            },
            0
        );
        assert_ne!(
            unsafe {
                AddAccessAllowedAceEx(
                    dacl,
                    ACL_REVISION,
                    0,
                    FILE_GENERIC_READ,
                    world.as_ptr().cast_mut().cast(),
                )
            },
            0
        );
        assert!(unsafe { dacl_grants_untrusted_access(dacl, current_user.sid()) });
    }

    #[test]
    fn retained_directory_opens_private_single_link_children() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let directory = open_private_state_directory(&root).expect("private directory");
        drop(directory);
        let directory = open_private_state_directory(&root).expect("reopen private directory");
        let file = open_private_state_child(&directory, "state.next", PrivateFileAccess::Create)
            .expect("private child");
        assert_eq!(
            winapi_util::file::information(&file)
                .expect("file information")
                .number_of_links(),
            1
        );
        assert!(private_state_child_exists(&directory, "state.next").expect("entry query"));
    }

    #[test]
    fn hard_link_is_rejected() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let directory = open_private_state_directory(&root).expect("private directory");
        drop(
            open_private_state_child(&directory, "state", PrivateFileAccess::Create)
                .expect("private child"),
        );
        std::fs::hard_link(root.join("state"), root.join("other")).expect("create hard link");
        assert!(open_private_state_child(&directory, "state", PrivateFileAccess::Read).is_err());
    }

    #[test]
    fn retained_directory_pins_root_and_ancestor_until_drop() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let ancestor = temporary.path().join("ancestor");
        std::fs::create_dir(&ancestor).expect("ancestor");
        let root = ancestor.join("registry");
        let directory = open_private_state_directory(&root).expect("private directory");
        assert!(std::fs::rename(&root, ancestor.join("moved-registry")).is_err());
        assert!(std::fs::rename(&ancestor, temporary.path().join("moved-ancestor")).is_err());

        // Pinning the owner directory must not prevent durable child replacement.
        let mut next =
            open_private_state_child(&directory, "state.next", PrivateFileAccess::Create)
                .expect("private child");
        std::io::Write::write_all(&mut next, b"committed").expect("write state");
        next.sync_all().expect("sync state");
        replace_private_state_child(&directory, "state.next", "state").expect("replace state");
        directory.sync_all().expect("sync directory");
        assert_eq!(
            std::fs::read(root.join("state")).expect("read state"),
            b"committed"
        );
        drop(next);
        drop(directory);
        let moved_root = ancestor.join("moved-registry");
        std::fs::rename(&root, &moved_root).expect("root released after drop");
        std::fs::rename(&ancestor, temporary.path().join("moved-ancestor"))
            .expect("ancestor released after drop");
    }
