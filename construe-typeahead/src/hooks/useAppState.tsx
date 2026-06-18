import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  DEFAULT_SETTINGS,
  type CodedConcept,
  type CommittedEntry,
  type FieldKind,
  type Settings,
} from '../types';
import { clearToken } from '../api/construe';

// Seed Settings from Vite env vars (.env) when present, else DEFAULT_SETTINGS.
// Keeping the Settings shape stable lets a localStorage build swap only the
// storage layer without touching these signatures.
function initialSettings(): Settings {
  return {
    clientId: import.meta.env.VITE_PHENOML_CLIENT_ID ?? DEFAULT_SETTINGS.clientId,
    clientSecret:
      import.meta.env.VITE_PHENOML_CLIENT_SECRET ?? DEFAULT_SETTINGS.clientSecret,
    baseUrl: import.meta.env.VITE_PHENOML_BASE_URL || DEFAULT_SETTINGS.baseUrl,
  };
}

let idCounter = 0;
function makeId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  idCounter += 1;
  return `e${idCounter}`;
}

interface AppState {
  // Config
  settings: Settings;
  updateSettings: (next: Settings) => void;
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
  const [settings, setSettings] = useState<Settings>(initialSettings);
  const [demoMode, setDemoMode] = useState(true); // Demo Mode default ON
  const [showCodes, setShowCodes] = useState(false); // hidden by default
  const [entries, setEntries] = useState<CommittedEntry[]>([]);

  const updateSettings = useCallback((next: Settings) => {
    // Credentials/host changed → drop any cached token so the next live call
    // re-authenticates against the new instance.
    clearToken();
    setSettings(next);
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
      settings,
      updateSettings,
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
      settings,
      updateSettings,
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
