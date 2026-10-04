use std::path::PathBuf;

use super::FileInputError;
use super::FileInputIntent;
use super::FileInputTarget;
use super::accept_file_input_result;
use super::active_file_input;
use super::arm_file_input;
use super::cancel_file_input;

fn absolute_path(name: &str) -> PathBuf {
    #[cfg(windows)]
    {
        PathBuf::from(format!(r"C:\hepta-native\{name}"))
    }
    #[cfg(not(windows))]
    {
        PathBuf::from(format!("/tmp/hepta-native/{name}"))
    }
}

#[cfg(unix)]
#[test]
fn drop_rejects_lossy_path_conversion_without_consuming_the_exact_intent() {
    use std::ffi::OsString;
    use std::os::unix::ffi::OsStringExt as _;

    let mut intent = FileInputIntent::default();
    let ticket = intent.arm(FileInputTarget::OperationGrant).unwrap();
    let non_utf8 = PathBuf::from(OsString::from_vec(b"/tmp/grant.\xff.json".to_vec()));
    assert_eq!(
        intent.accept(ticket, FileInputTarget::OperationGrant, &[Some(non_utf8)]),
        Err(FileInputError::NonUtf8Path)
    );
    assert_eq!(intent.active(), Some(ticket));
    let exact = absolute_path(" grant.json ");
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::OperationGrant,
            &[Some(exact.clone())]
        ),
        Ok(exact)
    );
}

#[test]
fn dropped_path_bound_is_checked_before_consuming_the_target() {
    let mut intent = FileInputIntent::default();
    let ticket = intent.arm(FileInputTarget::UpdateManifest).unwrap();
    let excessive = absolute_path(&"a".repeat(crate::model::MAX_NATIVE_PATH_BYTES + 1));
    assert_eq!(
        intent.accept(ticket, FileInputTarget::UpdateManifest, &[Some(excessive)]),
        Err(FileInputError::PathTooLong)
    );
    assert_eq!(intent.active(), Some(ticket));
}

#[test]
fn file_input_success_is_single_use_and_requires_an_absolute_path() {
    let mut intent = FileInputIntent::default();
    let ticket = intent.arm(FileInputTarget::UpdateManifest).unwrap();
    let selected = absolute_path("manifest.json");
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(selected.clone())]
        ),
        Ok(selected)
    );
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(absolute_path("manifest-2.json"))]
        ),
        Err(FileInputError::NoActiveIntent)
    );
}

#[test]
fn cancelled_or_replaced_file_input_rejects_stale_results() {
    let mut intent = FileInputIntent::default();
    let cancelled = intent.arm(FileInputTarget::OperationGrant).unwrap();
    assert_eq!(intent.cancel(), Some(cancelled));
    let current = intent.arm(FileInputTarget::UpdatePackage).unwrap();

    assert_eq!(
        intent.accept(
            cancelled,
            FileInputTarget::OperationGrant,
            &[Some(absolute_path("grant.json"))]
        ),
        Err(FileInputError::StaleIntent)
    );
    assert_eq!(intent.active(), Some(current));
    assert_eq!(
        intent.accept(
            current,
            FileInputTarget::UpdatePackage,
            &[Some(absolute_path("package.zip"))]
        ),
        Ok(absolute_path("package.zip"))
    );
}

#[test]
fn callback_results_are_bound_to_the_exact_context_ticket() {
    let context = eframe::egui::Context::default();
    let cancelled = arm_file_input(&context, FileInputTarget::OperationGrant).unwrap();
    assert_eq!(cancel_file_input(&context), Some(cancelled));
    let current = arm_file_input(&context, FileInputTarget::UpdateManifest).unwrap();

    assert_eq!(
        accept_file_input_result(
            &context,
            cancelled,
            FileInputTarget::OperationGrant,
            &[Some(absolute_path("stale-grant.json"))]
        ),
        Err(FileInputError::StaleIntent)
    );
    assert_eq!(active_file_input(&context), Some(current));
    assert_eq!(
        accept_file_input_result(
            &context,
            current,
            FileInputTarget::UpdatePackage,
            &[Some(absolute_path("wrong-package.zip"))]
        ),
        Err(FileInputError::WrongTarget {
            expected: FileInputTarget::UpdateManifest,
            actual: FileInputTarget::UpdatePackage,
        })
    );
    assert_eq!(active_file_input(&context), Some(current));
    assert_eq!(
        accept_file_input_result(
            &context,
            current,
            FileInputTarget::UpdateManifest,
            &[Some(absolute_path("manifest.json"))]
        ),
        Ok(absolute_path("manifest.json"))
    );
    assert_eq!(active_file_input(&context), None);
}

#[test]
fn wrong_target_and_invalid_drop_do_not_consume_the_active_intent() {
    let mut intent = FileInputIntent::default();
    let ticket = intent.arm(FileInputTarget::UpdateManifest).unwrap();

    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdatePackage,
            &[Some(absolute_path("package.zip"))]
        ),
        Err(FileInputError::WrongTarget {
            expected: FileInputTarget::UpdateManifest,
            actual: FileInputTarget::UpdatePackage,
        })
    );
    assert_eq!(intent.active(), Some(ticket));

    assert_eq!(
        intent.accept(ticket, FileInputTarget::UpdateManifest, &[]),
        Err(FileInputError::InvalidSelectionCount { actual: 0 })
    );
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(absolute_path("one")), Some(absolute_path("two"))]
        ),
        Err(FileInputError::InvalidSelectionCount { actual: 2 })
    );
    assert_eq!(
        intent.accept(ticket, FileInputTarget::UpdateManifest, &[None]),
        Err(FileInputError::MissingFilesystemPath)
    );
    assert_eq!(
        intent.accept(
            ticket,
            FileInputTarget::UpdateManifest,
            &[Some(PathBuf::from("relative.json"))]
        ),
        Err(FileInputError::RelativePath)
    );
    assert_eq!(intent.active(), Some(ticket));
}
