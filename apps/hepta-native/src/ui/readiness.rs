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
pub(super) struct ReadinessFrames {
    previous: Option<(u64, Identity)>,
}

pub(super) struct RenderedViewWitness(Identity);

impl ReadinessFrames {
    pub(super) fn reset(&mut self) {
        self.previous = None;
    }

    pub(super) fn observe(
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
    pub(super) fn verify_current(&self, runtime: &NativeShellRuntime) -> Result<(), ShellError> {
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
mod tests {
    use super::*;

    fn view() -> RuntimeView {
        RuntimeView {
            session_id: "session.one".into(),
            session_generation: 1,
            generation: 1,
            revision: 1,
            digest: "1".repeat(64),
            modules: vec!["ui.native".into()],
        }
    }

    #[test]
    fn readiness_requires_later_callback_and_resets() {
        let mut frames = ReadinessFrames::default();
        let view = view();
        assert!(frames.observe(1, &view).unwrap().is_none());
        assert!(frames.observe(1, &view).is_err());
        frames
            .observe(2, &view)
            .unwrap()
            .unwrap()
            .verify_view(&view)
            .unwrap();
        frames.reset();
        assert!(frames.observe(3, &view).unwrap().is_none());
    }

    #[test]
    fn readiness_binds_every_view_axis() {
        let current = view();
        let mut frames = ReadinessFrames::default();
        frames.observe(1, &current).unwrap();
        let witness = frames.observe(2, &current).unwrap().unwrap();
        for axis in 0..6 {
            let mut changed = current.clone();
            match axis {
                0 => changed.session_id = "session.two".into(),
                1 => changed.session_generation += 1,
                2 => changed.generation += 1,
                3 => changed.revision += 1,
                4 => changed.digest = "2".repeat(64),
                _ => changed.modules = vec!["runtime.agentd".into()],
            }
            assert!(witness.verify_view(&changed).is_err());
            frames.reset();
            assert!(frames.observe(3, &current).unwrap().is_none());
            assert!(frames.observe(4, &changed).unwrap().is_none());
            assert!(frames.observe(5, &changed).unwrap().is_some());
        }
    }
}
