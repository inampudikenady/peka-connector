interface RefreshActionOptions<T> {
  load: () => Promise<T>;
  onStart: () => void;
  onSuccess: (value: T) => void;
  onError: (reason: unknown) => void;
  onSettled: () => void;
}

export function createRefreshAction<T>({
  load, onStart, onSuccess, onError, onSettled,
}: RefreshActionOptions<T>): () => Promise<void> {
  let inFlight: Promise<void> | null = null;
  return () => {
    if (inFlight) return inFlight;
    onStart();
    inFlight = load()
      .then(onSuccess)
      .catch(onError)
      .finally(() => {
        inFlight = null;
        onSettled();
      });
    return inFlight;
  };
}
