# Security

Never commit an AcoustID key, environment file, shell history, log, media filename inventory, or
production configuration. The application reads `ACOUSTID_API_KEY` from its environment and does
not accept the key as a command-line option.

If a key enters Git history, revoke it before publishing the repository. Removing it from the
latest revision is not sufficient.

For deployment, keep `/etc/music-processor.env` owned by root with mode `0600`. Start with
`--dry-run`, run the service as an unprivileged account that owns the relevant music directories,
and retain backups of the library.
