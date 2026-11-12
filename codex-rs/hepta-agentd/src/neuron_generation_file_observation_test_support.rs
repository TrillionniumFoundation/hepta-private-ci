//! Physical observation uses the existing generation actor without retaining it.

use std::io;

use tokio::sync::mpsc;
use tokio::sync::oneshot;

use crate::NeuronGenerationRuntimeHandleV2;
use crate::neuron_generation_runtime::GenerationCommand;
use crate::neuron_generation_runtime::Response;

pub(crate) struct FileObserver {
    sender: mpsc::WeakSender<GenerationCommand>,
}

impl FileObserver {
    pub(crate) fn new(handle: &NeuronGenerationRuntimeHandleV2) -> Self {
        Self {
            sender: handle.sender.downgrade(),
        }
    }

    pub(crate) async fn journal_bytes(&self) -> io::Result<Vec<u8>> {
        self.call(GenerationCommand::QualificationJournalBytes)
            .await
    }

    pub(crate) async fn durable_bytes(&self) -> io::Result<[Vec<u8>; 3]> {
        self.call(GenerationCommand::QualificationDurableBytes)
            .await
    }

    async fn call<T>(
        &self,
        command: impl FnOnce(Response<io::Result<T>>) -> GenerationCommand,
    ) -> io::Result<T> {
        let sender = self.sender.upgrade().ok_or_else(|| {
            io::Error::new(io::ErrorKind::BrokenPipe, "generation owner is closed")
        })?;
        let (reply, response) = oneshot::channel();
        sender
            .try_send(command(reply))
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => io::Error::new(
                    io::ErrorKind::WouldBlock,
                    "generation observation queue is full",
                ),
                mpsc::error::TrySendError::Closed(_) => {
                    io::Error::new(io::ErrorKind::BrokenPipe, "generation owner is closed")
                }
            })?;
        drop(sender);
        response
            .await
            .map_err(|_| {
                io::Error::new(
                    io::ErrorKind::BrokenPipe,
                    "generation observation response is closed",
                )
            })?
            .map_err(io::Error::other)?
    }
}

impl NeuronGenerationRuntimeHandleV2 {
    pub(crate) async fn qualification_journal_bytes_for_test(&self) -> io::Result<Vec<u8>> {
        FileObserver::new(self).journal_bytes().await
    }

    pub(crate) async fn qualification_durable_bytes_for_test(&self) -> io::Result<[Vec<u8>; 3]> {
        FileObserver::new(self).durable_bytes().await
    }
}
