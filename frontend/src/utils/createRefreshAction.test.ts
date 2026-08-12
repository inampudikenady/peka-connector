import { describe, expect, it, vi } from 'vitest';

import { createRefreshAction } from './createRefreshAction';

interface KnowledgeSummary { documents: number; chunks: number }

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('knowledge store manual refresh', () => {
  it('updates displayed statistics from fresh backend state', async () => {
    let backend = { documents: 0, chunks: 0 };
    let displayed: KnowledgeSummary = backend;
    const refresh = createRefreshAction({
      load: async () => backend,
      onStart: () => undefined,
      onSuccess: (value) => { displayed = value; },
      onError: () => undefined,
      onSettled: () => undefined,
    });

    await refresh();
    backend = { documents: 1, chunks: 2 };
    await refresh();

    expect(displayed).toEqual({ documents: 1, chunks: 2 });
  });

  it('coalesces duplicate requests while refresh is pending', async () => {
    const request = deferred<KnowledgeSummary>();
    const load = vi.fn(() => request.promise);
    let refreshing = false;
    const refresh = createRefreshAction({
      load,
      onStart: () => { refreshing = true; },
      onSuccess: () => undefined,
      onError: () => undefined,
      onSettled: () => { refreshing = false; },
    });

    const first = refresh();
    const duplicate = refresh();
    expect(load).toHaveBeenCalledOnce();
    expect(refreshing).toBe(true);
    request.resolve({ documents: 1, chunks: 2 });
    await Promise.all([first, duplicate]);
    expect(refreshing).toBe(false);
  });

  it('keeps previous values and becomes available after failure', async () => {
    const request = deferred<KnowledgeSummary>();
    const previous = { documents: 1, chunks: 2 };
    let displayed = previous;
    let refreshing = false;
    let error = '';
    const refresh = createRefreshAction({
      load: () => request.promise,
      onStart: () => { refreshing = true; },
      onSuccess: (value) => { displayed = value; },
      onError: (reason) => { error = reason instanceof Error ? reason.message : 'Refresh failed'; },
      onSettled: () => { refreshing = false; },
    });

    const result = refresh();
    request.reject(new Error('Backend unavailable'));
    await result;

    expect(displayed).toBe(previous);
    expect(error).toBe('Backend unavailable');
    expect(refreshing).toBe(false);
  });
});
