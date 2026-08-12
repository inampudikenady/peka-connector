import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ManagedDocument } from '../api/types';
import { LEGACY_SOURCES_REDIRECT, navigationItems } from '../components/navigationItems';
import { documentDeletionAction } from '../utils/documents';
import { formatTimestamp, relativeTimestamp } from '../utils/time';
import {
  DOCUMENT_TABS,
  DocumentActions,
  DocumentVisibilityControl,
} from './DocumentsPage';

function managedDocument(overrides: Partial<ManagedDocument> = {}): ManagedDocument {
  return {
    id: 'document-id',
    source_id: 'source-id',
    document_key: 'uploaded-documents/example.txt',
    relative_path: 'example.txt',
    filename: 'example.txt',
    normalized_filename: 'example.txt',
    extension: '.txt',
    mime_type: 'text/plain',
    size_bytes: 12,
    content_hash: 'a'.repeat(64),
    modified_at: '2026-07-21T10:30:00Z',
    discovered_at: '2026-07-21T10:30:00Z',
    first_seen_at: '2026-07-21T10:30:00Z',
    last_seen_at: '2026-07-21T10:30:00Z',
    state: 'active',
    local_status: 'UPLOADED',
    delivery_status: 'UPLOADED',
    knowledge_status: 'INDEXED',
    indexed_chunk_count: 3,
    knowledge_error: null,
    upload_attempt_count: 1,
    last_upload_attempt_at: null,
    uploaded_at: null,
    remote_document_id: null,
    remote_version_id: null,
    last_error_code: null,
    last_error_message: null,
    created_at: '2026-07-21T10:30:00Z',
    updated_at: '2026-07-21T10:30:00Z',
    deleted_at: null,
    entry_method: 'DIRECT_COPY',
    can_delete: true,
    delete_unavailable_reason: null,
    deletion_in_progress: false,
    ...overrides,
  };
}

describe('Documents UI', () => {
  it('exposes customer-resident Documents as a primary connector page', () => {
    expect(navigationItems.find((item) => item.label === 'Integrations')?.path).toBe('/integrations');
    expect(navigationItems.some((item) => item.label === 'Data & Sync')).toBe(false);
    expect(navigationItems.find((item) => item.label === 'Documents')?.path).toBe('/documents');
    expect(navigationItems.some((item) => item.label === 'Sources')).toBe(false);
    expect(LEGACY_SOURCES_REDIRECT).toBe('/documents');
    expect(DOCUMENT_TABS).toEqual(['Files', 'Source settings']);
  });

  it('uses browser-local timestamp helpers without changing relative time', () => {
    const timestamp = '2026-07-21T10:30:00Z';
    expect(relativeTimestamp(timestamp, Date.parse('2026-07-21T10:33:00Z'))).toBe('3 minutes ago');
    expect(formatTimestamp(timestamp, 'Never', { timeZone: 'Asia/Kolkata' })).not.toBe(
      formatTimestamp(timestamp, 'Never', { timeZone: 'America/Los_Angeles' }),
    );
  });

  it('keeps the controlled path out of navigation and user inputs', () => {
    const markup = renderToStaticMarkup(<span>No documents have been added yet.</span>);
    expect(markup).toContain('No documents have been added yet.');
    expect(markup).not.toContain('/data/sources/documents');
  });

  it('shows delete for every eligible active file type and entry method', () => {
    for (const extension of ['.txt', '.pdf', '.docx', '.xlsx']) {
      for (const entry_method of ['UI_UPLOAD', 'DIRECT_COPY', 'EXTERNAL_SOURCE']) {
        expect(documentDeletionAction(managedDocument({ extension, entry_method }))).toEqual({
          visible: true,
          disabled: false,
          tooltip: 'Delete document',
        });
      }
    }
  });

  it('keeps details available while hiding delete for a deleted document', () => {
    const document = managedDocument({
      state: 'missing',
      local_status: 'DELETED',
      delivery_status: 'DELETED',
      deleted_at: '2026-07-21T10:35:00Z',
      can_delete: false,
      delete_unavailable_reason: 'This document has already been deleted.',
    });
    const markup = renderToStaticMarkup(
      <DocumentActions
        admin
        document={document}
        onDelete={() => undefined}
        onDetails={() => undefined}
        onRetry={() => undefined}
      />,
    );
    expect(markup).toContain('Details for example.txt');
    expect(markup).not.toContain('Delete example.txt');
  });

  it('shows a disabled delete action with a reason for invalid legacy ownership', () => {
    const document = managedDocument({
      can_delete: false,
      delete_unavailable_reason: 'Document ownership cannot be safely established.',
    });
    const action = documentDeletionAction(document);
    expect(action).toMatchObject({ visible: true, disabled: true });
    expect(action.tooltip).toContain('ownership');
  });

  it('renders the deleted-document control unchecked by default and checked on demand', () => {
    const unchecked = renderToStaticMarkup(
      <DocumentVisibilityControl showDeleted={false} onChange={() => undefined} />,
    );
    const checked = renderToStaticMarkup(
      <DocumentVisibilityControl showDeleted onChange={() => undefined} />,
    );
    expect(unchecked).toContain('Show deleted documents');
    expect(unchecked).not.toContain('checked=""');
    expect(checked).toContain('checked=""');
  });
});
