import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { AboutDetails } from './AboutPage';

describe('About page', () => {
  it('renders the connector version supplied by the runtime API', () => {
    const markup = renderToStaticMarkup(<AboutDetails version="1.2.3" />);
    expect(markup).toContain('Version 1.2.3');
  });
});
