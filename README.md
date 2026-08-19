# Music Upload Processor

Music Upload Processor turns completed MeTube audio downloads into a consistently tagged and
organised music library. It uses existing tags first, AcoustID fingerprints when tags are
incomplete, and MusicBrainz to locate the earliest official studio album for the underlying song.

The project is designed for unattended processing of inconsistent YouTube metadata. Upload noise
such as `Official Video`, `Lyrics`, `HD`, and `4K` is removed. Recording details such as live,
acoustic, demo, remix, edit, instrumental, and remaster information are preserved in the displayed
title.

When a download is a full album rather than a single track, the filename fallback separates an
uploader prefix from the credited artist and verifies the album title against MusicBrainz before
filing it. This keeps channel names out of artist metadata when fingerprinting is unavailable.

A live performance can therefore be organised alongside its studio counterpart:

```text
Radiohead/Pablo Honey/Creep.mp3
Radiohead/Pablo Honey/Creep (Live at Glastonbury 1997).mp3
```

The studio title `Creep` is used for the album lookup, while the complete live title is written to
the file and used in its path.

Track credits and album artists are separate. A track credited to
`Metallica feat. Marianne Faithfull` can be filed under the album artist `Metallica`. Commas are
not treated as artist separators, so names such as `Tyler, The Creator` remain intact.

## File handling

- Completed MP3 files are tagged and moved into `Album artist/Album/Title.mp3`.
- Completed JPEG, PNG, and WebP thumbnail sidecars are removed after a stability check.
- `.part`, `.ytdl`, and `.tmp` files are left untouched.
- Symlinks, unsupported formats, and files that cannot be tagged are moved into reason-specific
  directories under the failed-file path.
- Name collisions retain both files by adding `(2)`, `(3)`, and so on. The processor never assumes
  that matching artist and title strings prove two recordings are duplicates.
- A repeated download is removed only when its source identity and acoustic content match an
  existing import. If improved metadata changes the destination, the registered source is safely
  replaced at the corrected path. Different or unverified audio is retained for review.
- Every successful import can be recorded as JSON Lines, including its metadata source, confidence,
  original title, source URL, destination, and available external identifiers.
- Artist, album artist, album, and title each retain their own provenance so later corrections can
  distinguish existing tags, filename evidence, AcoustID matches, MusicBrainz matches, and fallbacks.

MeTube should use a temporary directory below its private state directory rather than the watched
upload directory. For example:

```yaml
STATE_DIR: /downloads/.metube
TEMP_DIR: /downloads/.metube/temp
```

## Requirements

- Python 3.11 or newer
- `fpcalc` from Chromaprint
- An [AcoustID application API key](https://acoustid.org/new-application)
- MeTube configured to produce MP3 files

On Debian or Ubuntu:

```console
sudo apt install libchromaprint-tools python3-venv
```

On Arch Linux:

```console
sudo pacman -S chromaprint python
```

## Installation

```console
python3 -m venv .venv
.venv/bin/pip install .
```

Provide the API key through the environment. Do not put a real key in source control or pass it as
a command-line argument.

```console
export ACOUSTID_API_KEY="replace-with-your-key"
.venv/bin/music-processor --dry-run
.venv/bin/music-processor
```

The default paths match a library mounted at `/mnt/music`:

| Purpose | Default | Environment variable |
| --- | --- | --- |
| Incoming files | `/mnt/music/uploads` | `MUSIC_UPLOADS_DIR` |
| Organised library | `/mnt/music/Music` | `MUSIC_LIBRARY_DIR` |
| Failed files | `/mnt/music/failed` | `MUSIC_QUARANTINE_DIR` |
| Instance lock | User runtime or temporary directory | `MUSIC_PROCESSOR_LOCK_FILE` |
| Decision log | Disabled | `MUSIC_PROCESSOR_DECISION_LOG` |
| Source registry | `/mnt/music/.processor/sources.db` | `MUSIC_PROCESSOR_SOURCE_DB` |
| Fallback album | `Singles & Miscellaneous` | `MUSIC_PROCESSOR_FALLBACK_ALBUM` |
| MusicBrainz contact | Project URL | `MUSICBRAINZ_CONTACT` |
| Log level | `INFO` | `MUSIC_PROCESSOR_LOG_LEVEL` |
| Dry-run mode | Disabled | `MUSIC_PROCESSOR_DRY_RUN` |

Command-line path options override the corresponding environment variables. Run
`music-processor --help` for the complete interface.

Inspect quarantined files without modifying them:

```console
.venv/bin/music-processor --report-quarantine
```

## Systemd deployment

The files in [`deploy/systemd`](deploy/systemd) run the processor once per minute as the `mop`
user. Install the project under `/opt/music-processor`, create its virtual environment, and install
the units:

```console
sudo install -m 600 deploy/systemd/music-processor.env.example /etc/music-processor.env
sudoedit /etc/music-processor.env
sudo install -m 644 deploy/systemd/music-processor.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/music-processor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now music-processor.timer
```

The example environment enables dry-run mode. Review the journal before changing it to `false`:

```console
sudo systemctl start music-processor.service
journalctl -u music-processor.service
```

## Development

```console
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest
```

## License

Copyright (C) 2026 THE-M0P

This project is licensed under the GNU Affero General Public License, version 3 only. See
[`LICENSE`](LICENSE) for the complete terms.
