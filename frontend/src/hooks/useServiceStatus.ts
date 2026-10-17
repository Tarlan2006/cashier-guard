import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "../api";
import type { Health, Readiness } from "../api";
export function useServiceStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [checked, setChecked] = useState(false);
  const [version, setVersion] = useState(0);
  const sequence = useRef(0);
  useEffect(() => {
    const run = ++sequence.current,
      cancel = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      const [server, ready] = await Promise.allSettled([
        request<Health>("/health", "", {
          signal: cancel.signal,
          timeoutMs: 4_000,
          retries: 1,
        }),
        request<Readiness>("/ready", "", {
          signal: cancel.signal,
          timeoutMs: 6_000,
          retries: 1,
        }),
      ]);
      if (cancel.signal.aborted || run !== sequence.current) return;
      setHealth(server.status === "fulfilled" ? server.value : null);
      setReadiness(ready.status === "fulfilled" ? ready.value : null);
      setChecked(true);
      timer = setTimeout(check, 15_000);
    };
    void check();
    return () => {
      cancel.abort();
      clearTimeout(timer);
    };
  }, [version]);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  return { health, readiness, checked, refresh };
}
