import { describe, expect, it } from 'vitest';

import { passwordsMatch, splitPatterns } from './forms';

describe('form helpers', () => {
  it('normalizes newline and comma separated source patterns', () => {
    expect(splitPatterns('**/*.pdf\n **/*.md,\n**/*.txt')).toEqual([
      '**/*.pdf', '**/*.md', '**/*.txt',
    ]);
  });

  it('requires a non-empty exact password confirmation', () => {
    expect(passwordsMatch('Strong!Password123', 'Strong!Password123')).toBe(true);
    expect(passwordsMatch('Strong!Password123', 'different')).toBe(false);
    expect(passwordsMatch('', '')).toBe(false);
  });
});
