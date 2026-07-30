import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { CMDBDataset } from '../api/types';
import { cmdbImportMode } from '../utils/cmdb';
import { CMDBImportModeField } from './CMDBPage';

const dataset: CMDBDataset = {
  id: 'dataset-id',
  name: 'Production assets',
  status: 'active',
  current_version_id: 'version-id',
  current_version: 1,
  source_filename: 'assets.csv',
  imported_at: '2026-07-29T00:00:00Z',
  total_rows: 1,
  valid_rows: 1,
  invalid_rows: 0,
  updated_at: '2026-07-29T00:00:00Z',
};

describe('CMDB import mode', () => {
  it('shows Create new dataset as the selected default when it is the only mode', () => {
    const markup = renderToStaticMarkup(
      <CMDBImportModeField
        datasets={[]}
        selectedDatasetId=""
        onChange={() => undefined}
      />,
    );
    expect(markup).toContain('Import mode');
    expect(markup).toContain('Create new dataset');
    expect(markup).toContain('aria-disabled="true"');
    expect(markup).not.toContain('Append records');
    expect(markup).not.toContain('Update existing records');
  });

  it('keeps the accessible selector enabled when new-version choices exist', () => {
    const markup = renderToStaticMarkup(
      <CMDBImportModeField
        datasets={[dataset]}
        selectedDatasetId=""
        onChange={() => undefined}
      />,
    );
    expect(markup).toContain('role="combobox"');
    expect(markup).toContain('Create new dataset');
    expect(markup).not.toContain('aria-disabled="true"');
  });

  it('submits the matching backend mode for create and new-version flows', () => {
    expect(cmdbImportMode('')).toBe('create_new');
    expect(cmdbImportMode(dataset.id)).toBe('new_version');
  });
});
