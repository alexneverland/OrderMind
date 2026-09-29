import { useCallback, useEffect, useRef, useState } from "react";

export function useAsync<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError("");
    setData(null);
    try {
      const value = await load();
      if (current === generation.current) setData(value);
    } catch (e) {
      if (current === generation.current)
        setError(e instanceof Error ? e.message : "Request failed");
      throw e;
    } finally {
      if (current === generation.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    void refresh().catch(() => {});
  }, [refresh]);
  return { data, error, loading, refresh, setData };
}
