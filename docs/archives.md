# Archived versions

All imported source snapshots can be browsed at the immutable
[`archive/software-inventory-2026-10-28`](https://github.com/nataliehuhn/microscope-software/tree/archive/software-inventory-2026-10-28) tag. Its `sources/` directory keeps
each original folder separate; `manifests/` records original paths, byte sizes,
SHA-256 hashes and inclusion/exclusion reasons. Snapshots are reference material,
not additional supported installations. The two partial Mic3 backups are not
complete applications.

| Source group | Preserved folders |
| --- | --- |
| Mic2 | `codex-microscope-software`, `leica_microscope`, `leica_microscope_old` |
| Mic3 | `codex-microscope-software`, `leica_microscope`, `leica_microscope_old`, `fast_scan_version` |
| Mic3 partial backups | `mic3_before_fast_scan_20261023_113223`, `mic3_before_position_fix_20261023_121926` |
| Auxiliary and older tools | `deflinator`, `gridviewer`, `old/MicroscopeToolsProject` |

The latest source imports before organization also have dedicated tags:

- [`archive/mic2-import-2026-10-28`](https://github.com/nataliehuhn/microscope-software/tree/archive/mic2-import-2026-10-28)
- [`archive/mic3-import-2026-10-28`](https://github.com/nataliehuhn/microscope-software/tree/archive/mic3-import-2026-10-28)

## Full local backups

On the migration PC, full ZIP snapshots of the nine `C:\Software` folders are
stored in:

```
C:\Users\User\Documents\ChatGPT\github_microscope_software\.migration\archives
```

These preserve original Git/Mercurial metadata, runtime files and installed
third-party software. Their CRCs and SHA-256 hashes were checked during import.
They are deliberately outside Git. Keep this directory when retaining the
migration backup; a fresh GitHub clone will not contain it.

Mic2 ZIPs are **source-only** snapshots. Its complete copied folders remain at:

```
\\131.188.117.91\biophysDS4\transfer\microscope-software-migration-20261028-mic2
```

The original Mic2 directories also remain on that PC. Acquired images, memory
maps, caches, vendor installers and repositories' internal metadata are not
published as current source. No original installed folder was removed or renamed.
`docs/archive-inventory.json` lists ZIP hashes and source-file counts.

## Recover an old source version

Use a separate folder so the working microscope installation is unaffected:

```powershell
git clone --branch archive/mic3-import-2026-10-28 https://github.com/nataliehuhn/microscope-software.git microscope-software-mic3-import
```

An archive-tag checkout is detached. Inspect and validate it before use on hardware.
The inventory tag is an archive index, not a runnable microscope branch.
