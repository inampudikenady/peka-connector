# Database

PEKA Connector uses a local SQLite database through SQLAlchemy 2.x. Alembic is the sole schema migration mechanism. Containers run `alembic upgrade head` before the API starts.

## Tables

### `users`

Stores UUID, unique username, Argon2 password hash, active flag, and creation time. Plaintext passwords and JWTs are never stored.

### `sources`

Stores UUID, stable plugin type, administrator-facing name, enabled flag, normalized JSON configuration, and timestamps. JSON keeps the source envelope generic while each plugin retains strict Pydantic validation.

### `documents`

Stores a source foreign key and discovered metadata: relative path, filename, extension, size, modification time, SHA-256, and discovery time. `(source_id, relative_path)` is unique. Deleting a source cascades to its metadata.

## Transaction behavior

A successful scan replaces one source's document snapshot in one transaction. Discovery and hashing occur before the transaction begins, avoiding a long SQLite write lock. If discovery fails, existing metadata remains available.

SQLite foreign keys are enabled on every connection. The connector currently assumes one writing backend process. Network filesystems are not supported for the SQLite volume; use a local durable Docker volume or VM disk.

## Backup and migration

Stop the backend or use SQLite's supported online backup mechanism before copying the database. Protect backups as configuration secrets may be present in plugin JSON in future releases. Upgrade procedures must back up the database, pull the new signed image, and let Alembic migrate forward. Downgrades are development aids and are not a substitute for restore testing.

