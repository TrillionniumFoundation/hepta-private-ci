use super::*;

fn apartment() -> Apartment {
    // SAFETY: Each test owns this thread's apartment until its later-declared
    // COM interfaces have dropped; no interface crosses a thread boundary.
    unsafe {
        CoInitializeEx(/*pvreserved*/ None, COINIT_APARTMENTTHREADED).ok()
    }
    .unwrap();
    Apartment
}

fn fixture() -> (tempfile::TempDir, PathBuf, PathBuf) {
    let directory = tempfile::tempdir().unwrap();
    let executable = directory.path().join("Hepta 用户.exe");
    std::fs::write(&executable, b"owned target; never executed").unwrap();
    // Exercise the production register/save/readback path. Only destination
    // discovery is supplied by the fixture; the Start Menu is never accessed.
    let shortcut = register_in(&executable, || Ok(directory.path().to_path_buf())).unwrap();
    (directory, executable, shortcut)
}

fn load(shortcut: &Path) -> IShellLinkW {
    let path = wide(shortcut.as_os_str()).unwrap();
    // SAFETY: Callers hold an apartment; the bounded string stays live for Load.
    unsafe {
        let link: IShellLinkW =
            CoCreateInstance(&ShellLink, /*punkouter*/ None, CLSCTX_INPROC_SERVER).unwrap();
        let persist: IPersistFile = link.cast().unwrap();
        persist.Load(PCWSTR(path.as_ptr()), STGM_READ).unwrap();
        link
    }
}

fn save(link: &IShellLinkW, shortcut: &Path) {
    let path = wide(shortcut.as_os_str()).unwrap();
    let persist: IPersistFile = link.cast().unwrap();
    // SAFETY: Callers retain the apartment and link; the output is fixture-owned.
    unsafe {
        persist.Save(PCWSTR(path.as_ptr()), /*fremember*/ true)
    }
    .unwrap();
}

#[test]
fn registrar_diagnostic_preserves_hresult_without_source_details() {
    let _apartment = apartment();
    let source_details = "C:\\用户\\private.exe; identity=private-value; ".repeat(1_024);
    for code in [
        windows::Win32::Foundation::E_FAIL,
        windows::Win32::Foundation::E_ACCESSDENIED,
    ] {
        let source = windows::core::Error::new(code, &source_details);
        let error = registration_error("registrar SetPath", source);
        assert_eq!(
            (error.code(), error.message(), error.to_string()),
            (
                code,
                "registrar SetPath".to_owned(),
                format!("registrar SetPath ({code})"),
            )
        );
    }
}

#[test]
fn rust_registrar_round_trips_owned_shortcut_with_native_property_store() {
    let (_directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    let link = load(&shortcut);
    let store: IPropertyStore = link.cast().unwrap();
    // SAFETY: The store remains in its apartment; the SDK owns the returned value.
    let identity = unsafe { store.GetValue(&APP_USER_MODEL_ID_KEY) }.unwrap();
    assert_eq!(identity.vt(), windows::Win32::System::Variant::VT_LPWSTR);
    let mut target = [0_u16; 32_768];
    // SAFETY: The writable buffer is live and its size is passed by the projection.
    unsafe {
        link.GetPath(&mut target, std::ptr::null_mut(), /*fflags*/ 0)
    }
    .unwrap();
    let length = target.iter().position(|value| *value == 0).unwrap();
    let target = PathBuf::from(OsString::from_wide(&target[..length]));
    let executable_file = open_registration_target(&executable).unwrap();
    let target_file = open_registration_target(&target).unwrap();
    assert_eq!(
        (
            BSTR::try_from(&identity).unwrap().to_string(),
            file_identity(&target_file).unwrap(),
        ),
        (
            APP_USER_MODEL_ID.to_owned(),
            file_identity(&executable_file).unwrap()
        )
    );
}

#[test]
fn rust_registrar_rejects_persisted_identity_mismatch() {
    let (_directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    let executable_file = open_registration_target(&executable).unwrap();
    verify_saved_shortcut(&executable_file, &shortcut).unwrap();
    let link = load(&shortcut);
    let store: IPropertyStore = link.cast().unwrap();
    let text = wide(std::ffi::OsStr::new("Hepta.Fixture.WrongIdentity")).unwrap();
    // SAFETY: Strings, SDK-owned variants, interfaces, and apartment outlive calls.
    unsafe {
        let vector = InitPropVariantFromStringVector(Some(&[PCWSTR(text.as_ptr())])).unwrap();
        let value = InitPropVariantFromPropVariantVectorElem(&vector, /*ielem*/ 0).unwrap();
        store.SetValue(&APP_USER_MODEL_ID_KEY, &value).unwrap();
        store.Commit().unwrap();
    }
    save(&link, &shortcut);
    assert_eq!(
        verify_saved_shortcut(&executable_file, &shortcut).unwrap_err(),
        "native notification identity registration: registrar persisted identity mismatch (0x80004005)"
    );
    // A positive control makes the failure specific to the persisted identity.
    unsafe {
        store
            .SetValue(&APP_USER_MODEL_ID_KEY, &app_id_value().unwrap())
            .unwrap();
        store.Commit().unwrap();
    }
    save(&link, &shortcut);
    verify_saved_shortcut(&executable_file, &shortcut).unwrap();
}

#[test]
fn rust_registrar_rejects_persisted_target_mismatch() {
    let (directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    let other = directory.path().join("other.exe");
    std::fs::write(&other, b"other owned target; never executed").unwrap();
    let executable_file = open_registration_target(&executable).unwrap();
    let other_file = open_registration_target(&other).unwrap();
    let other_text = wide(other.as_os_str()).unwrap();
    let link = load(&shortcut);
    // SAFETY: The apartment and bounded target string remain live.
    unsafe { link.SetPath(PCWSTR(other_text.as_ptr())) }.unwrap();
    save(&link, &shortcut);
    assert_eq!(
        verify_saved_shortcut(&executable_file, &shortcut).unwrap_err(),
        "native notification identity registration: registrar persisted target file identity mismatch (0x80004005)"
    );
    // The same stored shortcut is valid for its actual target and identity.
    verify_saved_shortcut(&other_file, &shortcut).unwrap();
}

#[test]
fn rust_registrar_accepts_case_and_hard_link_aliases_of_the_same_file() {
    let (directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    let hard_link = directory.path().join("same-file-alias.exe");
    std::fs::hard_link(&executable, &hard_link).unwrap();
    let executable_file = open_registration_target(&executable).unwrap();
    let link = load(&shortcut);
    for alias in [directory.path().join("hEPTA 用户.EXE"), hard_link] {
        assert_ne!(alias, executable);
        let alias_file = open_registration_target(&alias).unwrap();
        assert_eq!(
            file_identity(&executable_file).unwrap(),
            file_identity(&alias_file).unwrap()
        );
        let path = wide(alias.as_os_str()).unwrap();
        // SAFETY: This apartment owns the link and the bounded alias is live.
        unsafe { link.SetPath(PCWSTR(path.as_ptr())) }.unwrap();
        save(&link, &shortcut);
        verify_saved_shortcut(&executable_file, &shortcut).unwrap();
    }
}

#[test]
fn rust_registrar_accepts_short_names_when_the_filesystem_provides_them() {
    let (_directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    let path = wide(executable.as_os_str()).unwrap();
    let mut long = [0_u16; 32_768];
    // SAFETY: The source is NUL-terminated and the projection bounds the output.
    let long_length = unsafe {
        windows::Win32::Storage::FileSystem::GetLongPathNameW(
            PCWSTR(path.as_ptr()),
            Some(&mut long),
        )
    } as usize;
    assert!(long_length > 0 && long_length < long.len());
    let long_path = PathBuf::from(OsString::from_wide(&long[..long_length]));
    let mut short = [0_u16; 32_768];
    // SAFETY: The source is NUL-terminated and the projection bounds the output.
    let length = unsafe {
        windows::Win32::Storage::FileSystem::GetShortPathNameW(
            PCWSTR(long.as_ptr()),
            Some(&mut short),
        )
    } as usize;
    assert!(length > 0 && length < short.len());
    let alias = PathBuf::from(OsString::from_wide(&short[..length]));
    if alias == long_path {
        // Windows explicitly allows volumes without 8.3 names. Report the
        // missing subcase; mandatory case/hard-link alias tests still execute.
        eprintln!("UNEXERCISED: filesystem provides no distinct 8.3 alias for registrar fixture");
        return;
    }
    let executable_file = open_registration_target(&executable).unwrap();
    let alias_file = open_registration_target(&alias).unwrap();
    assert_eq!(
        file_identity(&executable_file).unwrap(),
        file_identity(&alias_file).unwrap()
    );
    let link = load(&shortcut);
    // SAFETY: The apartment owns the link and the short-name buffer is live.
    unsafe { link.SetPath(PCWSTR(short.as_ptr())) }.unwrap();
    save(&link, &shortcut);
    verify_saved_shortcut(&executable_file, &shortcut).unwrap();
    eprintln!("EXERCISED: distinct 8.3 alias passed registrar file-identity verification");
}

#[test]
fn rust_registrar_retains_expected_file_against_write_delete_and_rename() {
    let directory = tempfile::tempdir().unwrap();
    let executable = directory.path().join("retained.exe");
    std::fs::write(&executable, b"original").unwrap();
    let replacement = directory.path().join("moved.exe");
    register_in(&executable, || {
        assert!(
            std::fs::OpenOptions::new()
                .write(true)
                .open(&executable)
                .is_err()
        );
        assert!(std::fs::remove_file(&executable).is_err());
        assert!(std::fs::rename(&executable, &replacement).is_err());
        assert_eq!(std::fs::read(&executable).unwrap(), b"original");
        Ok(directory.path().to_path_buf())
    })
    .unwrap();
    // Registration releases its handle only after save, readback and sync.
    std::fs::write(&executable, b"released").unwrap();
    std::fs::rename(&executable, &replacement).unwrap();
    std::fs::remove_file(&replacement).unwrap();
}

#[test]
fn rust_registrar_rejects_reparse_targets_before_and_after_save() {
    let (directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    let executable_file = open_registration_target(&executable).unwrap();
    let redirected = directory.path().join("redirected.exe");
    std::fs::write(&redirected, b"different file").unwrap();
    let path = wide(redirected.as_os_str()).unwrap();
    let link = load(&shortcut);
    // SAFETY: The apartment owns the link and the bounded path remains live.
    unsafe { link.SetPath(PCWSTR(path.as_ptr())) }.unwrap();
    save(&link, &shortcut);
    drop(link);
    std::fs::remove_file(&redirected).unwrap();
    std::os::windows::fs::symlink_file(&executable, &redirected).unwrap();
    assert!(
        register_in(&redirected, || {
            panic!("reparse target must fail before destination lookup")
        })
        .is_err()
    );
    assert!(open_registration_target(&redirected).is_err());
    assert_eq!(
        verify_saved_shortcut(&executable_file, &shortcut).unwrap_err(),
        "native notification identity registration: registrar observed target open (0x80004005)"
    );
    assert_eq!(
        std::fs::read(&executable).unwrap(),
        b"owned target; never executed"
    );
}

#[test]
fn rust_registrar_rejects_directory_target_and_shortcut_without_overwriting() {
    let directory = tempfile::tempdir().unwrap();
    assert!(
        register_in(directory.path(), || {
            panic!("invalid executable must fail before destination lookup")
        })
        .is_err()
    );
    let executable = directory.path().join("fixture.exe");
    std::fs::write(&executable, b"owned target; never executed").unwrap();
    let shortcut = directory.path().join("Hepta Native.lnk");
    std::fs::create_dir(&shortcut).unwrap();
    std::fs::write(shortcut.join("owned.txt"), b"preserve").unwrap();
    assert!(register_in(&executable, || Ok(directory.path().to_path_buf())).is_err());
    assert_eq!(
        std::fs::read(shortcut.join("owned.txt")).unwrap(),
        b"preserve"
    );
}

#[test]
fn native_sdk_owns_string_property_variant_and_roundtrip() {
    let value = app_id_value().unwrap();
    assert_eq!(value.vt(), windows::Win32::System::Variant::VT_LPWSTR);
    assert_eq!(
        BSTR::try_from(&value).unwrap().to_string(),
        APP_USER_MODEL_ID
    );
}

#[test]
fn native_path_input_preserves_unicode_and_rejects_embedded_nul() {
    let value = std::ffi::OsStr::new("C:\\用户\\Hepta Native.exe");
    let encoded = wide(value).unwrap();
    assert_eq!(OsString::from_wide(&encoded[..encoded.len() - 1]), value);
    assert!(wide(&OsString::from_wide(&[65, 0, 66])).is_err());
}
