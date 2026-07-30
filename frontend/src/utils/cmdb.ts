import type { CMDBImportMode } from '../api/types';

export function cmdbImportMode(datasetId: string): CMDBImportMode {
  return datasetId ? 'new_version' : 'create_new';
}
