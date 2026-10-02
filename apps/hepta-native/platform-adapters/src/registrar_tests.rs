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
    assert_eq!(
        (
            BSTR::try_from(&identity).unwrap().to_string(),
            OsString::from_wide(&target[..length]),
        ),
        (APP_USER_MODEL_ID.to_owned(), executable.into_os_string())
    );
}

#[test]
fn rust_registrar_rejects_persisted_identity_mismatch() {
    let (_directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    verify_saved_shortcut(&executable, &shortcut).unwrap();
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
    assert!(verify_saved_shortcut(&executable, &shortcut).is_err());
    // A positive control makes the failure specific to the persisted identity.
    unsafe {
        store
            .SetValue(&APP_USER_MODEL_ID_KEY, &app_id_value().unwrap())
            .unwrap();
        store.Commit().unwrap();
    }
    save(&link, &shortcut);
    verify_saved_shortcut(&executable, &shortcut).unwrap();
}

#[test]
fn rust_registrar_rejects_persisted_target_mismatch() {
    let (directory, executable, shortcut) = fixture();
    let _apartment = apartment();
    let other = directory.path().join("other.exe");
    std::fs::write(&other, b"other owned target; never executed").unwrap();
    let other_text = wide(other.as_os_str()).unwrap();
    let link = load(&shortcut);
    // SAFETY: The apartment and bounded target string remain live.
    unsafe { link.SetPath(PCWSTR(other_text.as_ptr())) }.unwrap();
    save(&link, &shortcut);
    assert!(verify_saved_shortcut(&executable, &shortcut).is_err());
    // The same stored shortcut is valid for its actual target and identity.
    verify_saved_shortcut(&other, &shortcut).unwrap();
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
