import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  type CodedConcept,
  type CommittedEntry,
  type FieldKind,
} from '../types';
import { fetchLiveConfig } from '../api/construe';

let idCounter = 0;
function makeId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  idCounter += 1;
  return `e${idCounter}`;
}

interface AppState {
  // Config — credentials live server-side (.env); the browser only learns
  // whether Live mode is available, never the secret.
  liveAvailable: boolean;
  demoMode: boolean;
  setDemoMode: (on: boolean) => void;
  showCodes: boolean;
  setShowCodes: (on: boolean) => void;

  // Committed-code store
  entries: CommittedEntry[];
  commit: (kind: FieldKind, text: string, codes: CodedConcept[]) => void;
  removeEntry: (id: string) => void;
  clearEntries: () => void;
  entriesByKind: (kind: FieldKind) => CommittedEntry[];
}

const AppStateContext = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [liveAvailable, setLiveAvailable] = useState(false);
  const [demoMode, setDemoMode] = useState(true); // Demo Mode default ON
  const [showCodes, setShowCodes] = useState(false); // hidden by default
  const [entries, setEntries] = useState<CommittedEntry[]>([]);

  // Ask the proxy once whether credentials are configured server-side.
  useEffect(() => {
    let cancelled = false;
    fetchLiveConfig().then((cfg) => {
      if (cancelled) return;
      setLiveAvailable(cfg.live);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const commit = useCallback(
    (kind: FieldKind, text: string, codes: CodedConcept[]) => {
      setEntries((prev) => [...prev, { id: makeId(), kind, text, codes }]);
    },
    [],
  );

  const removeEntry = useCallback((id: string) => {
    setEntries((prev) => prev.filter((e) => e.id !== id));
  }, []);

  const clearEntries = useCallback(() => setEntries([]), []);

  const entriesByKind = useCallback(
    (kind: FieldKind) => entries.filter((e) => e.kind === kind),
    [entries],
  );

  const value = useMemo<AppState>(
    () => ({
      liveAvailable,
      demoMode,
      setDemoMode,
      showCodes,
      setShowCodes,
      entries,
      commit,
      removeEntry,
      clearEntries,
      entriesByKind,
    }),
    [
      liveAvailable,
      demoMode,
      showCodes,
      entries,
      commit,
      removeEntry,
      clearEntries,
      entriesByKind,
    ],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider');
  return ctx;
}
