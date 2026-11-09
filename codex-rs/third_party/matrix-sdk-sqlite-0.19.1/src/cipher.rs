// Copyright 2022 The Matrix.org Foundation C.I.C.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//! Cipher CPU work has no database handle or write capability.

use base64::Engine as _;
use matrix_sdk_store_encryption::{Error, StoreCipher};
use vodozemac::base64_encode;
use zeroize::Zeroizing;

use crate::{Base64Variant, OpenStoreError, Secret};

pub(crate) async fn open(
    secret: Secret,
    encrypted: Option<Vec<u8>>,
) -> Result<(StoreCipher, Option<Vec<u8>>), OpenStoreError> {
    run(move || prepare(secret, encrypted)).await
}

async fn run<T: Send + 'static>(
    operation: impl FnOnce() -> Result<T, Error> + Send + 'static,
) -> Result<T, OpenStoreError> {
    // Use the existing Tokio executor, not a new pool. A started worker can
    // outlive a cancelled waiter, but it owns only crypto inputs. Its Secret
    // remains zeroizing until completion; it cannot publish a cipher to SQLite.
    tokio::task::spawn_blocking(operation)
        .await
        .map_err(OpenStoreError::CipherTask)?
        .map_err(OpenStoreError::InitCipher)
}

fn prepare(
    secret: Secret,
    encrypted: Option<Vec<u8>>,
) -> Result<(StoreCipher, Option<Vec<u8>>), Error> {
    if let Some(encrypted) = encrypted {
        match &secret {
            Secret::PassPhrase(passphrase) => {
                Ok((StoreCipher::import(passphrase, &encrypted)?, None))
            }
            Secret::Key(key) => {
                Ok((StoreCipher::import_with_key(key.as_slice(), &encrypted)?, None))
            }
            Secret::HighEntropyPassPhrase { key, base64_variant } => {
                match StoreCipher::import_with_key(key.as_slice(), &encrypted) {
                    Ok(cipher) => Ok((cipher, None)),
                    Err(Error::KdfMismatch) => {
                        // Preserve both historical base64 encodings. Only this
                        // legacy branch returns a replacement encrypted export.
                        let passphrase = Zeroizing::new(match base64_variant {
                            Base64Variant::Unpadded => base64_encode(key),
                            Base64Variant::Padded => base64::prelude::BASE64_STANDARD.encode(key),
                        });
                        let cipher = StoreCipher::import(&passphrase, &encrypted);
                        drop(passphrase);
                        let cipher = cipher?;
                        let export = cipher.export_with_key(key.as_slice())?;
                        Ok((cipher, Some(export)))
                    }
                    Err(error) => Err(error),
                }
            }
        }
    } else {
        let cipher = StoreCipher::new()?;
        let export = match &secret {
            Secret::PassPhrase(passphrase) => {
                #[cfg(not(test))]
                {
                    cipher.export(passphrase)
                }
                #[cfg(test)]
                {
                    cipher._insecure_export_fast_for_testing(passphrase)
                }
            }
            Secret::Key(key) | Secret::HighEntropyPassPhrase { key, .. } => {
                cipher.export_with_key(key.as_slice())
            }
        }?;
        Ok((cipher, Some(export)))
    }
}

#[cfg(test)]
#[path = "cipher_tests.rs"]
mod tests;
