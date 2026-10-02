use std::path::PathBuf;

use windows::Win32::Foundation::ERROR_CANCELLED;
use windows::Win32::System::Com::CLSCTX_INPROC_SERVER;
use windows::Win32::System::Com::COINIT_APARTMENTTHREADED;
use windows::Win32::System::Com::COINIT_DISABLE_OLE1DDE;
use windows::Win32::System::Com::CoCreateInstance;
use windows::Win32::System::Com::CoInitializeEx;
use windows::Win32::System::Com::CoTaskMemFree;
use windows::Win32::System::Com::CoUninitialize;
use windows::Win32::UI::Shell::FOS_ALLOWMULTISELECT;
use windows::Win32::UI::Shell::FOS_DONTADDTORECENT;
use windows::Win32::UI::Shell::FOS_FILEMUSTEXIST;
use windows::Win32::UI::Shell::FOS_FORCEFILESYSTEM;
use windows::Win32::UI::Shell::FOS_NOCHANGEDIR;
use windows::Win32::UI::Shell::FOS_NODEREFERENCELINKS;
use windows::Win32::UI::Shell::FOS_PATHMUSTEXIST;
use windows::Win32::UI::Shell::FileOpenDialog;
use windows::Win32::UI::Shell::IFileOpenDialog;
use windows::Win32::UI::Shell::SIGDN_FILESYSPATH;
use windows::core::HRESULT;
use windows::core::PWSTR;
use windows::core::w;

struct Apartment;
impl Drop for Apartment {
    fn drop(&mut self) {
        // SAFETY: This stack-local guard is created only after successful STA
        // initialization and cannot escape the helper's single thread.
        unsafe { CoUninitialize() };
    }
}

struct DisplayName(PWSTR);
impl Drop for DisplayName {
    fn drop(&mut self) {
        // SAFETY: GetDisplayName transfers one CoTaskMem-owned allocation.
        // This sole guard releases it exactly once, including decode failures.
        unsafe { CoTaskMemFree(Some(self.0.as_ptr().cast())) };
    }
}

pub(super) fn choose_file() -> Result<Option<PathBuf>, String> {
    choose().map_err(|error| format!("native Windows file picker: {error}"))
}

fn choose() -> windows::core::Result<Option<PathBuf>> {
    // SAFETY: All COM objects are owned within this fresh STA on one thread;
    // generated bindings provide valid interface IDs and static title storage.
    unsafe {
        CoInitializeEx(None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE).ok()?;
        let _apartment = Apartment;
        let dialog: IFileOpenDialog =
            CoCreateInstance(&FileOpenDialog, None, CLSCTX_INPROC_SERVER)?;
        let options = (dialog.GetOptions()? & !FOS_ALLOWMULTISELECT)
            | FOS_FORCEFILESYSTEM
            | FOS_FILEMUSTEXIST
            | FOS_PATHMUSTEXIST
            | FOS_NOCHANGEDIR
            | FOS_DONTADDTORECENT
            | FOS_NODEREFERENCELINKS;
        dialog.SetOptions(options)?;
        dialog.SetTitle(w!("Select a Hepta input file"))?;
        if let Err(error) = dialog.Show(None) {
            return if error.code() == HRESULT::from_win32(ERROR_CANCELLED.0) {
                Ok(None)
            } else {
                Err(error)
            };
        }
        let item = dialog.GetResult()?;
        let name = DisplayName(item.GetDisplayName(SIGDN_FILESYSPATH)?);
        if name.0.is_null() {
            return Err(windows::core::Error::from_hresult(
                windows::Win32::Foundation::E_FAIL,
            ));
        }
        // The OS owns the valid terminated allocation until DisplayName drops.
        // Strict UTF-16 conversion rejects unpaired surrogates instead of
        // substituting a different filename before the Rust owner reopens it.
        let path = name.0.to_string().map_err(|_| {
            windows::core::Error::from_hresult(windows::Win32::Foundation::E_INVALIDARG)
        })?;
        Ok(Some(PathBuf::from(path)))
    }
}
