# Fritz.Wulf `fw`

`fw` is the device-aware Fritz.Wulf package-manager client for FRITZ!Box and Freetz-NG environments.

Canonical repository index:

`https://fritz-wulf.github.io/repo/index.json`

Human-readable catalog:

`https://fritz-wulf.github.io/repo/`

## Current status

Version `0.2.0` remains non-installing and non-flashing, but adds explicit artifact verification. It can identify the local platform, refresh repository metadata, list/search package records, inspect package information, and verify an exact package version by size and SHA-256 before any future installation workflow exists.

Entry points are equivalent:

```sh
fw
fwulf
fritzwulf
```

## Commands

```text
fw version
fw repo
fw device
fw doctor
fw update
fw list
fw search <query>
fw info <package>
fw verify <package> <version>
```

Global options currently include `--json` and `--quiet`.

## Repository model

`fw update` downloads both `index.json` and the generated `Packages` compatibility feed into an atomic local cache. `index.json` remains the canonical public data contract; `Packages` is generated from the same metadata and provides a small POSIX/awk-friendly view for early router clients.

Historical source snapshots remain visible but are not silently treated as installable packages.

## Safety

- No command in this foundation release performs firmware flashing.
- Unknown devices are reported as `unknown`, never guessed from an IP address.
- Repository refresh is atomic; incomplete downloads are not activated.
- Future install operations must verify size, SHA-256, signature, architecture, device profile, and dependencies before activation.

## Development

```sh
sh -n bin/fw bin/fwulf bin/fritzwulf
python3 -m unittest -q tests.test_fw
```

See `AGENTS.md` for the full development and release contract.