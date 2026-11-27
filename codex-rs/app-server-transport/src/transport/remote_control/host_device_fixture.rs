use std::future::Future;

tokio::task_local! {
    static FIXED_HOST_DEVICE_KIND: Option<&'static str>;
}

/// A parsed hardware profile scoped to one test controller, without changing the shared detector.
#[derive(Clone, Copy)]
pub(in crate::transport::remote_control) struct HostDeviceKindFixture(Option<&'static str>);

impl HostDeviceKindFixture {
    pub(in crate::transport::remote_control) fn from_profile(
        profile: &[u8],
    ) -> serde_json::Result<Self> {
        super::host_device_kind_from_profile(profile).map(Self)
    }

    pub(in crate::transport::remote_control) fn scope<F: Future>(
        self,
        future: F,
    ) -> impl Future<Output = F::Output> {
        FIXED_HOST_DEVICE_KIND.scope(self.0, future)
    }
}

pub(in crate::transport::remote_control) fn current() -> Option<Option<&'static str>> {
    FIXED_HOST_DEVICE_KIND.try_with(|kind| *kind).ok()
}

pub(in crate::transport::remote_control) fn inherit_for_controller<F>(
    future: F,
) -> impl Future<Output = F::Output> + Send
where
    F: Future + Send,
{
    // Task locals do not cross spawn. Capture while the caller's scope is active, then restore it
    // whenever this controller is polled, including later websocket retries.
    let fixed = current();
    async move {
        match fixed {
            Some(kind) => FIXED_HOST_DEVICE_KIND.scope(kind, future).await,
            None => future.await,
        }
    }
}

#[path = "host_device_fixture_tests.rs"]
mod tests;
