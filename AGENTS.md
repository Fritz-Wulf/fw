# AGENTS.md — Fritz.Wulf `fw`

## Purpose

`fw`, `fwulf`, and `fritzwulf` are equivalent entry points to the Fritz.Wulf package-manager/runtime client. The canonical package index is `https://fritz-wulf.github.io/repo/index.json`.

## Non-negotiable safety rules

- A normal `fw` invocation must never flash firmware.
- Package/runtime updates and firmware build/flash are separate operations.
- Never infer hardware identity from an IP address alone.
- Unknown architecture, ABI, device profile, checksum, or signature state must fail closed.
- Never publish secrets, credentials, private keys, internal infrastructure identifiers, or private logs.
- Never overwrite unrelated user or agent changes.

## Device model

Support is profile-driven. Minimum target families are FRITZ!Box 3270, 7490, 7530, and 7590. Verify model, hardware revision where available, CPU architecture, endianness, kernel, libc, FRITZ!OS, Freetz/Freetz-NG context, package architecture, and ABI independently.

The 7490 / FRITZ!OS 07.62 / MIPS32 big-endian / Linux 3.10.107 / uClibc combination is a historical verified reference, not a universal assumption.

## Repository contract

`index.json` is the single source of truth. The generated `Packages` feed may be used as a POSIX-friendly compatibility representation but must never be maintained independently.

Every installable artifact needs provenance, size, SHA-256, compatibility, dependencies, and verification metadata. Historical source snapshots remain `installable: false` until a reproducible package is verified.
## Development workflow

Use branches named `agent/<work-area>-YYYYMMDD`. Before edits inspect status, branch, log, and remotes. Implement behavior test-first, run fresh verification before commits/PRs, and merge only with green CI.

Do not use `git reset --hard`, `git clean -fdx`, or force-push without an exceptional documented reason.

## Required behaviors

Foundation/read-only commands:

- `version`
- `repo`
- `device`
- `doctor`
- `update`
- `list`
- `search`
- `info`

Future transactional commands include install, upgrade, downgrade, remove, reinstall, verify, pin/unpin, history, and rollback. They must download to temporary storage, verify before activation, and preserve rollback state.

## CLI contract

Respect automation: stable exit codes, no ANSI in JSON mode, `NO_COLOR`, explicit errors, and no silent fallback from verification failures. `--yes` may never disable safety checks.

## Releases

All published `fw` versions must remain discoverable in `https://fritz-wulf.github.io/repo/` and `index.json`. Release ingestion into `Fritz-Wulf/repo` must be additive; duplicate name/version/architecture tuples are errors.