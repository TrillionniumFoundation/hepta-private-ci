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

use base64::Engine as _;
use matrix_sdk_store_encryption::StoreCipher;
use vodozemac::base64_encode;
use zeroize::Zeroize;

use crate::{OpenStoreError, Secret, cipher_task};

/// Compute the cipher and an optional export without retaining a database handle.
///
/// The four independently opened stores can await their password derivations
/// concurrently instead of blocking the async task polling all four futures.
/// Only the awaiting caller may save the returned export. Cancelling it aborts
/// queued work; running work finishes without a database write and its owned
/// secret and unclaimed cipher are dropped with their existing zeroization.
pub(crate) async fn load_or_create(
    secret: Secret,
    encrypted: Option<Vec<u8>>,
) -> Result<(StoreCipher, Option<Vec<u8>>), OpenStoreError> {
    cipher_task::run(move || {
        if let Some(encrypted) = encrypted {
            let cipher = match &secret {
                Secret::PassPhrase(passphrase) => StoreCipher::import(passphrase, &encrypted)?,
                Secret::Key(key) => StoreCipher::import_with_key(key.as_slice(), &encrypted)?,
                Secret::HighEntropyPassPhrase { key, base64_variant } => {
                    // Element X used a base64-encoded random key as a passphrase.
                    // Preserve its existing migration to the key-based export.
                    match StoreCipher::import_with_key(key.as_slice(), &encrypted) {
                        Ok(cipher) => cipher,
                        Err(matrix_sdk_store_encryption::Error::KdfMismatch) => {
                            let mut passphrase = match base64_variant {
                                crate::Base64Variant::Unpadded => base64_encode(key),
                                crate::Base64Variant::Padded => {
                                    base64::prelude::BASE64_STANDARD.encode(key)
                                }
                            };
                            let cipher = StoreCipher::import(&passphrase, &encrypted);
                            passphrase.zeroize();
                            let cipher = cipher?;
                            let export = cipher.export_with_key(key.as_slice())?;
                            return Ok((cipher, Some(export)));
                        }
                        Err(error) => return Err(error.into()),
                    }
                }
            };
            Ok((cipher, None))
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
                Secret::Key(key) => cipher.export_with_key(key.as_slice()),
                Secret::HighEntropyPassPhrase { key, .. } => cipher.export_with_key(key.as_slice()),
            }?;
            Ok((cipher, Some(export)))
        }
    })
    .await
    .map_err(OpenStoreError::CipherTask)?
}
