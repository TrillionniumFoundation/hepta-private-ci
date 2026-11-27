//! One in-process Model response borrows the original material connection.
//! Begin/Pages precede its tentative effect; the same transfer's actual Finish
//! follows it. Cancellation or failure drops the sole channel without rearming.
use super::*;

/// The fields and constructor stay private to the original material client.
/// This cannot be cloned, serialized, stored by the client, or sent on the wire.
pub(crate) struct OriginalCellEvaluationModelReadV1<'a> {
    client: OriginalMaterialReadClient<'a>,
    channel: Channel,
    material: OriginalCellEvaluationModelMaterialV1,
    transfer: u64,
    started_at: u64,
    cancellation: Cancelled,
}

enum OriginalMaterialReadClient<'a> {
    Borrowed(&'a OriginalCellEvaluationModelMaterialClientV1),
    Owned(Arc<OriginalCellEvaluationModelMaterialClientV1>),
}
impl OriginalMaterialReadClient<'_> {
    fn original(&self) -> &OriginalCellEvaluationModelMaterialClientV1 {
        match self {
            Self::Borrowed(original) => original,
            Self::Owned(original) => original.as_ref(),
        }
    }
}

impl OriginalCellEvaluationModelMaterialClientV1 {
    /// The same retained client and sole transfer, with ownership only to
    /// avoid a self-reference in one bounded native Model response.
    pub(crate) async fn begin_owned_model_read(
        self: Arc<Self>,
    ) -> Result<OriginalCellEvaluationModelReadV1<'static>, Error> {
        let operation = self.begin_model_read().await?;
        let OriginalCellEvaluationModelReadV1 {
            client: _,
            channel,
            material,
            transfer,
            started_at,
            cancellation,
        } = operation;
        Ok(OriginalCellEvaluationModelReadV1 {
            client: OriginalMaterialReadClient::Owned(self),
            channel,
            material,
            transfer,
            started_at,
            cancellation,
        })
    }

    pub(crate) async fn begin_model_read(
        &self,
    ) -> Result<OriginalCellEvaluationModelReadV1<'_>, Error> {
        self.begin_model_read_with_clock(now).await
    }

    async fn begin_model_read_with_clock(
        &self,
        mut clock: impl FnMut() -> Result<u64, Error> + Send,
    ) -> Result<OriginalCellEvaluationModelReadV1<'_>, Error> {
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        let started_at = clock()?;
        require_clock(self.observed_at, started_at)?;
        if wire::context_binding(&self.context, started_at)? != self.binding {
            return Err(Error::CommitUncertain);
        }
        let expected = self
            .expected
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .clone();
        if let Some(original) = &expected {
            wire::binding(&self.context, original, started_at)?;
        }
        let transfer = channel.next;
        let cancellation = Cancelled(Arc::new(AtomicBool::new(/*v*/ false)));
        let cancelled = Arc::clone(&cancellation.0);
        let binding = self.binding;
        let result = tokio::task::spawn_blocking(move || {
            let bytes = read_pages(&mut channel, binding, &cancelled)?;
            channel.peer.check_peer_lifetime()?;
            Ok::<_, Error>((channel, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        let (channel, bytes) = match result {
            Err(Error::Missing | Error::Pending) if expected.is_some() => {
                return Err(Error::CommitUncertain);
            }
            result => result?,
        };
        let current = clock()?;
        require_clock(started_at, current)?;
        let material = self.authenticate_material(bytes, &expected, current)?;
        if self
            .retained
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .is_some_and(|original| original != material.binding())
        {
            return Err(Error::CommitUncertain);
        }
        Ok(OriginalCellEvaluationModelReadV1 {
            client: OriginalMaterialReadClient::Borrowed(self),
            channel,
            material,
            transfer,
            started_at,
            cancellation,
        })
    }
}

impl OriginalCellEvaluationModelReadV1<'_> {
    /// Preserve the original peer/pidfd and absolute connection lifetime
    /// across the same native operation. This is not a completed Finish.
    pub(crate) fn require_original_operation_current(&self, lower: u64) -> Result<u64, Error> {
        self.channel.peer.check_peer_lifetime()?;
        let current = now()?;
        require_clock(self.started_at.max(lower), current)?;
        let client = self.client.original();
        if wire::context_binding(&client.context, current)? != client.binding {
            return Err(Error::CommitUncertain);
        }
        self.material.authenticate_current(current)?;
        Ok(current)
    }

    /// Borrow only inside this original Model response. This does not release
    /// the material or restore the connection before its actual Finish.
    pub(crate) fn material(&self) -> &OriginalCellEvaluationModelMaterialV1 {
        &self.material
    }

    pub(crate) async fn finish(self) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        self.finish_with_clock(now).await
    }

    async fn finish_with_clock(
        self,
        mut clock: impl FnMut() -> Result<u64, Error> + Send,
    ) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        let Self {
            client,
            mut channel,
            material,
            transfer,
            started_at,
            cancellation,
        } = self;
        let client = client.original();
        let cancelled = Arc::clone(&cancellation.0);
        let binding = client.binding;
        let result = tokio::task::spawn_blocking(move || {
            finish_transfer(&mut channel, binding, transfer, &material.bytes, &cancelled)?;
            channel.peer.check_peer_lifetime()?;
            Ok::<_, Error>((channel, material))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        let (channel, material) = result;
        let current = clock()?;
        require_clock(started_at, current)?;
        let material = client.retain_completed_material(channel, material, current)?;
        drop(cancellation);
        Ok(material)
    }
}

#[cfg(test)]
impl OriginalCellEvaluationModelMaterialClientV1 {
    pub(crate) async fn fixture_begin_model_read_at(
        &self,
        current: u64,
    ) -> Result<OriginalCellEvaluationModelReadV1<'_>, Error> {
        self.begin_model_read_with_clock(|| Ok(current)).await
    }
}

#[cfg(test)]
impl OriginalCellEvaluationModelReadV1<'_> {
    pub(crate) async fn fixture_finish_at(
        self,
        current: u64,
    ) -> Result<OriginalCellEvaluationModelMaterialV1, Error> {
        self.finish_with_clock(|| Ok(current)).await
    }
}
