//! Native activation from actual kernel roles and original persistent owners.
mod activation;
mod boot;
mod boundary;
mod cycle;
mod evidence;
mod ipc;
mod native_observer;
mod owner;
mod paths;
mod provision;
mod recovery;
mod recovery_process;
mod recovery_registration;
mod root;
mod supervisor;
mod workload;

pub(super) fn run() -> Result<(), Box<dyn std::error::Error>> {
    let boot = boot::Boot::read()?;
    match boot.role {
        boot::Role::Root => {
            let control = boot.open_control()?;
            root::run(boot, control)
        }
        boot::Role::Manager | boot::Role::Recovery => {
            let role = if boot.role == boot::Role::Manager {
                "manager"
            } else {
                "recovery"
            };
            let control = boot.open_control()?;
            owner::run(
                boot,
                control,
                &activation::path(role, "launch"),
                &activation::path(role, "requests"),
            )
        }
        boot::Role::Workload => workload::run(boot),
    }
}
