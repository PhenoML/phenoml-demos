import { useRef, useState } from 'react';
import { Box, Stack, Text, TextInput } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useTypeahead, type SearchMode } from '../hooks/useTypeahead';
import { useAppState } from '../hooks/useAppState';
import { CommittedEntry } from './CommittedEntry';
import { SuggestionList } from './SuggestionList';
import type { CodeSystemSlug, FieldKind, Suggestion } from '../types';
import { tokens } from '../theme';

interface RowBuilderProps {
  kind: FieldKind;
  systems: CodeSystemSlug[];
  mode?: SearchMode;
  label: string;
  hint: string;
  placeholder: string;
  minLength?: number;
  /** Strip parenthetical qualifiers from displayed labels/code descriptions. */
  cleanLabels?: boolean;
}

// Generic "type a phrase → pick a ranked suggestion → commit display text +
// code(s)" builder. Shared by problem list, medication, and orders fields.
export function RowBuilder({
  kind,
  systems,
  mode = 'text',
  label,
  hint,
  placeholder,
  minLength = 2,
  cleanLabels = false,
}: RowBuilderProps) {
  const { commit, showCodes, entriesByKind } = useAppState();
  const { query, setQuery, suggestions, loading, error, reset } = useTypeahead({
    systems,
    mode,
    minLength,
    cleanLabels,
  });
  const [focused, setFocused] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const entries = entriesByKind(kind);
  const open = focused && query.trim().length >= minLength;

  function accept(s: Suggestion) {
    commit(kind, s.label, s.codes);
    reset();
    setActiveIndex(0);
    inputRef.current?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || suggestions.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const choice = suggestions[Math.min(activeIndex, suggestions.length - 1)];
      if (choice) accept(choice);
    } else if (e.key === 'Escape') {
      reset();
    }
  }

  // Clamp the highlight in case the result set shrank since the last keystroke.
  const clampedActive =
    suggestions.length > 0 ? Math.min(activeIndex, suggestions.length - 1) : 0;

  return (
    <Box>
      <Text className="ct-eyebrow" c="slate.7" mb={4}>
        {label}
      </Text>
      <Text size="xs" c="slate.6" mb={8}>
        {hint}
      </Text>

      <Box style={{ position: 'relative' }}>
        <TextInput
          ref={inputRef}
          value={query}
          placeholder={placeholder}
          leftSection={<IconPlus size={16} />}
          onChange={(e) => {
            setQuery(e.currentTarget.value);
            setActiveIndex(0);
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={onKeyDown}
          size="md"
          radius="md"
          styles={{
            input: {
              borderColor: tokens.border,
              backgroundColor: tokens.surface,
              fontWeight: 500,
            },
          }}
        />
        {open && (
          <SuggestionList
            suggestions={suggestions}
            activeIndex={clampedActive}
            loading={loading}
            error={error}
            query={query}
            showCodes={showCodes}
            onHover={setActiveIndex}
            onSelect={accept}
          />
        )}
      </Box>

      {entries.length > 0 && (
        <Stack gap={8} mt={12}>
          {entries.map((entry) => (
            <CommittedEntry key={entry.id} entry={entry} />
          ))}
        </Stack>
      )}
    </Box>
  );
}
