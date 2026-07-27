# ADR-005: Filesystem Document Source

- Status: Accepted
- Date: 2026-07-20

## Context

The first connector source must inventory documents from administrator-approved local paths without taking over SaaS content-processing responsibilities.

## Decision

Implement a filesystem plugin supporting PDF, DOCX, TXT, and Markdown extensions. Restrict
absolute readable directories to the configured external source root (`/data/external-sources` in
Docker) or descendants, apply include/exclude globs, reject symlink escapes, do not follow
discovery symlinks, and collect relative path, filename, extension, size, modification time, and
SHA-256. Reconcile metadata with discovery/last-seen timestamps and active/missing state. Mount the
generic customer source tree read-only in Docker.

## Consequences

The connector can detect content changes without parsing or retaining content. Hashing reads every included file and may be I/O intensive; future incremental scans can reuse size, time, and prior hashes. Files that change or become inaccessible during discovery may be skipped until the next scan.
