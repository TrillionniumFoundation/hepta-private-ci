use std::ffi::OsStr;
use std::ffi::OsString;

use crate::AcceptanceError;

const FORMAL_ENVIRONMENT: [(&str, &str); 5] = [
    ("HEPTA_SSD_ROOT", "/Volumes/T5/hepta-vnext"),
    (
        "HEPTA_SSD_VOLUME_UUID",
        "FB804D1B-24CB-4D6E-AEA7-A9E180807758",
    ),
    ("HEPTA_LANE", "operator-acceptance"),
    (
        "HEPTA_WORKTREE",
        "/Volumes/T5/hepta-vnext/worktrees/operator-acceptance",
    ),
    ("HEPTA_ARTIFACTS_DIR", "/Volumes/T5/hepta-vnext/artifacts"),
];

pub fn require_formal_environment() -> Result<(), AcceptanceError> {
    validate_formal_environment_with(|name| std::env::var_os(name))
}

fn validate_formal_environment_with(
    lookup: impl Fn(&str) -> Option<OsString>,
) -> Result<(), AcceptanceError> {
    for (name, expected) in FORMAL_ENVIRONMENT {
        if lookup(name).as_deref() != Some(OsStr::new(expected)) {
            return Err(AcceptanceError::Invalid(format!(
                "formal operator acceptance requires exact {name} from hepta-ssd-run"
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::ffi::OsString;

    use super::FORMAL_ENVIRONMENT;
    use super::validate_formal_environment_with;

    #[test]
    fn every_missing_or_wrong_formal_environment_pin_is_rejected() {
        let exact = FORMAL_ENVIRONMENT.into_iter().collect::<BTreeMap<_, _>>();
        validate_formal_environment_with(|name| exact.get(name).map(OsString::from))
            .expect("exact wrapper environment");
        for name in exact.keys() {
            assert!(
                validate_formal_environment_with(|candidate| {
                    (candidate != *name)
                        .then(|| exact.get(candidate))
                        .flatten()
                        .map(OsString::from)
                })
                .is_err()
            );
            assert!(
                validate_formal_environment_with(|candidate| {
                    if candidate == *name {
                        Some(OsString::from("wrong"))
                    } else {
                        exact.get(candidate).map(OsString::from)
                    }
                })
                .is_err()
            );
        }
    }
}
