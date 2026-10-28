# Microscope software — Mic3

Leica microscope acquisition software with a Basler camera. This is the
**`mic3` branch**, containing Mic3's current imported software and calibration.

| Microscope | Branch | Connection | Latest source imported from |
| --- | --- | --- | --- |
| Mic2 | [`mic2`](https://github.com/nataliehuhn/microscope-software/tree/mic2) | COM3 | `D:\Chris\codex-microscope-software` |
| Mic3 | [`mic3`](https://github.com/nataliehuhn/microscope-software/tree/mic3) | COM4 | `C:\Software\codex-microscope-software` |

## Start here

1. Follow [setup and deployment](docs/setup.md) using the branch for the actual microscope.
2. Open **`start-live-view.bat`** for the live viewer or **`start-record.bat`** for the Record GUI.
3. Follow the [operation guide](docs/operation.md) for recording and projection scans.

Use a separate checkout for each microscope. Each branch carries its own
configuration, plate coordinates and velocity model. Existing installations
have been preserved; this repository has not been deployed over them.

## Repository guide

- [Code and folder map](docs/architecture.md)
- [Mic2 / Mic3 differences and consolidation plan](docs/microscope-comparison.md)
- [Old versions, backups and recovery](docs/archives.md)
- [Development and testing](docs/development.md)
- [Migration changes](CHANGELOG.md)
- [Original technical notes](docs/history/README-before-organization.md)

This migration unifies organization and documentation while preserving the two
hardware implementations. The automated tests use simulated hardware; a new
moving scan was not performed during repository preparation.

Based on [fabrylab/leica_microscope](https://github.com/fabrylab/leica_microscope).
The original [MIT license](LICENSE) and upstream history are retained.
