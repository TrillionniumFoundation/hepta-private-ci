//! GUI observations are not execution authority. A later callback witnesses that
//! the preceding callback returned; the worker rechecks the exact view before I/O.
use crate::error::ShellError;
use crate::model::RuntimeView;
use crate::runtime::NativeShellRuntime;

#[derive(Debug, Clone, PartialEq, Eq)]
struct Identity {
    session_id: String,
    session_generation: u64,
    generation: u64,
    revision: u64,
    digest: String,
    modules: Vec<String>,
}

impl Identity {
    fn from_view(view: &RuntimeView) -> Result<Self, ShellError> {
        view.validate()?;
        Ok(Self {
            session_id: view.session_id.clone(),
            session_generation: view.session_generation,
            generation: view.generation,
            revision: view.revision,
            digest: view.digest.clone(),
            modules: view.modules.clone(),
        })
    }
}

#[derive(Default)]
pub(crate) struct ReadinessFrames {
    previous: Option<(u64, Identity)>,
}

pub(crate) struct RenderedViewWitness(Identity);

impl ReadinessFrames {
    pub(crate) fn reset(&mut self) {
        self.previous = None;
    }

    pub(crate) fn observe(
        &mut self,
        frame: u64,
        view: &RuntimeView,
    ) -> Result<Option<RenderedViewWitness>, ShellError> {
        if frame == 0 || self.previous.as_ref().is_some_and(|(old, _)| frame <= *old) {
            return Err(ShellError::State(
                "readiness requires a later GUI callback".into(),
            ));
        }
        let identity = Identity::from_view(view)?;
        let ready = self
            .previous
            .as_ref()
            .is_some_and(|(_, old)| *old == identity);
        self.previous = Some((frame, identity.clone()));
        Ok(ready.then_some(RenderedViewWitness(identity)))
    }
}

impl RenderedViewWitness {
    pub(crate) fn verify_current(&self, runtime: &NativeShellRuntime) -> Result<(), ShellError> {
        let view = runtime
            .view()
            .ok_or_else(|| ShellError::State("readiness view expired".into()))?;
        self.verify_view(view)
    }

    fn verify_view(&self, view: &RuntimeView) -> Result<(), ShellError> {
        if Identity::from_view(view)? != self.0 {
            return Err(ShellError::State(
                "readiness witness does not match current view".into(),
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "readiness_tests.rs"]
mod tests;
