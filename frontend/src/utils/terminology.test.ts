import { describe, expect, it } from 'vitest';

import { customerFacingText } from './displayText';

const customerModules = {
  ...import.meta.glob('../pages/*.tsx', { eager: true, import: 'default', query: '?raw' }),
  ...import.meta.glob('../components/*.tsx', { eager: true, import: 'default', query: '?raw' }),
  ...import.meta.glob('./registration.ts', { eager: true, import: 'default', query: '?raw' }),
};

describe('customer terminology', () => {
  it('uses PEKA instead of SaaS in customer-facing copy', () => {
    for (const [path, module] of Object.entries(customerModules)) {
      if (path.includes('.test.')) continue;
      const source = String(module);
      expect(source, path).not.toContain('SaaS Registration');
      expect(source, path).not.toContain('SaaS URL');
      expect(source, path).not.toContain('PEKA SaaS');
    }
    expect(customerFacingText('PEKA SaaS is unavailable')).toBe('PEKA is unavailable');
  });
});
