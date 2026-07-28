import type { ManagedDocument } from '../api/types';

export function documentDeletionAction(document: ManagedDocument): {
  visible: boolean;
  disabled: boolean;
  tooltip: string;
} {
  if (document.can_delete) {
    return { visible: true, disabled: false, tooltip: 'Delete document' };
  }
  if (document.deletion_in_progress) {
    return {
      visible: true,
      disabled: true,
      tooltip: document.delete_unavailable_reason ?? 'Document deletion is already in progress.',
    };
  }
  if (
    document.delivery_status === 'DELETED'
    || ['deleted', 'tombstoned', 'missing'].includes(document.state.toLowerCase())
  ) {
    return { visible: false, disabled: true, tooltip: '' };
  }
  return {
    visible: true,
    disabled: true,
    tooltip: document.delete_unavailable_reason ?? 'Document deletion is unavailable.',
  };
}
