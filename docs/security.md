# Security model

## Enforced today

`fw update` activates repository metadata atomically. `fw verify <package> <version>` resolves an exact package stanza, downloads the referenced artifact into a temporary file, rejects unsafe relative paths, validates the declared byte size, and validates the declared SHA-256 before reporting success.

A checksum mismatch, size mismatch, missing metadata, missing SHA-256 implementation, unknown version, or failed download is fatal. No package is installed and no firmware is flashed.

## Repository signatures

Repository signatures are **not yet enforced**. SHA-256 protects against accidental corruption and detects content mismatch, but by itself does not authenticate a compromised repository endpoint.

The signed-repository phase must add a detached signature over a canonical repository manifest, keep the private signing key outside public GitHub repositories, publish only public verification material, support key rotation, and fail closed on missing or invalid signatures.

## Signature verifier discovery

`fw doctor` reports whether `usign`, `signify`, or `signify-openbsd` is available on the target system. This is capability discovery only; until repository signing is implemented and validated end-to-end, the client reports `signature enforcement: disabled` and does not claim authenticated repository metadata.
