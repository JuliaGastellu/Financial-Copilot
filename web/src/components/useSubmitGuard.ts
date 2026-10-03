import { useCallback, useRef, useState } from "react";

/**
 * Evito dobles envíos: el estado de React no se actualiza a tiempo entre dos clics
 * seguidos, así que uso una referencia síncrona además del estado visible.
 */
export function useSubmitGuard() {
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  const run = useCallback(async (task: () => Promise<void>) => {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    try {
      await task();
    } finally {
      busy.current = false;
      setPending(false);
    }
  }, []);
  return { run, pending };
}
