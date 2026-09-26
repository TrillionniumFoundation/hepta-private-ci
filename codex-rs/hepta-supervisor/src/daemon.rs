// Keep the established daemon implementation byte-identical and layer the
// runtime.fleet product admission scope around its public entry points. The
// low-level Unix process driver captures this immutable task-local scope when
// the daemon constructs it, so every actual spawn/adoption path is checked at
// the final effect boundary without introducing a second supervisor owner.
include!("daemon_core.rs");

/// Runs supervisord with an independently pinned runtime.fleet start-admission
/// profile. The profile is immutable for this daemon generation and is captured
/// by the process driver before any child recovery or spawn can occur.
pub async fn run_supervisord_with_fleet_start_admission(
    fleet_root: HeptaFleetRoot,
    cancellation: CancellationToken,
    verifier: Option<H7H89ProductionGrantVerifier>,
    admission: crate::FleetStartAdmission,
) -> Result<(), SupervisorError> {
    #[cfg(unix)]
    {
        return crate::unix::with_fleet_start_admission(admission, async move {
            match verifier {
                Some(verifier) => {
                    run_supervisord_with_grant_verifier(fleet_root, cancellation, verifier).await
                }
                None => run_supervisord(fleet_root, cancellation).await,
            }
        })
        .await;
    }

    #[cfg(not(unix))]
    {
        let _ = admission;
        match verifier {
            Some(verifier) => {
                run_supervisord_with_grant_verifier(fleet_root, cancellation, verifier).await
            }
            None => run_supervisord(fleet_root, cancellation).await,
        }
    }
}
