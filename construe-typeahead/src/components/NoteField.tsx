import { Box, Group, Stack, Text, Textarea } from '@mantine/core';
import { IconX } from '@tabler/icons-react';
import { useTypeahead } from '../hooks/useTypeahead';
import { useAppState } from '../hooks/useAppState';
import { ChipRail } from './ChipRail';
import type { CodeSystemSlug, Suggestion } from '../types';
import { tokens } from '../theme';

// Free-text note → SNOMED via SEMANTIC search (the clinician writes a phrase,
// not a prefix). Suggested concept chips appear beneath the field; tapping one
// commits a coded tag. Committed tags show their code when "Show codes" is on.
const NOTE_SYSTEMS: CodeSystemSlug[] = ['SNOMED_CT_US_LITE'];

export function NoteField() {
  const { commit, showCodes, entriesByKind, removeEntry } = useAppState();
  const { query, setQuery, suggestions, loading, error } = useTypeahead({
    systems: NOTE_SYSTEMS,
    mode: 'semantic',
    minLength: 3,
  });

  const tags = entriesByKind('note');
  const committedCodes = new Set(tags.map((t) => t.codes[0]?.code));

  function accept(s: Suggestion) {
    if (committedCodes.has(s.codes[0]?.code)) return; // avoid duplicate tags
    commit('note', s.label, s.codes);
  }

  return (
    <Box>
      <Text className="ct-eyebrow" c="slate.7" mb={4}>
        Clinical note
      </Text>
      <Text size="xs" c="slate.6" mb={8}>
        Write freely — semantic search finds SNOMED concepts by meaning, not spelling.
      </Text>

      <Textarea
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        placeholder="e.g. Patient reports shortness of breath on exertion and a dry cough."
        autosize
        minRows={3}
        radius="md"
        styles={{
          input: {
            borderColor: tokens.border,
            backgroundColor: tokens.surface,
            lineHeight: 1.55,
          },
        }}
      />

      <ChipRail
        suggestions={suggestions}
        loading={loading}
        error={error}
        hasQuery={query.trim().length >= 3}
        showCodes={showCodes}
        onTap={accept}
      />

      {tags.length > 0 && (
        <Stack gap={6} mt={14}>
          <Text className="ct-eyebrow" c="slate.7">
            Coded tags
          </Text>
          <Group gap={8}>
            {tags.map((tag) => {
              const code = tag.codes[0];
              return (
                <Group
                  key={tag.id}
                  gap={8}
                  wrap="nowrap"
                  style={{
                    padding: '5px 6px 5px 12px',
                    borderRadius: 999,
                    background: 'var(--mantine-color-teal-7)',
                  }}
                >
                  <Text size="sm" fw={600} c="white">
                    {tag.text}
                  </Text>
                  {showCodes && code && (
                    <Text
                      span
                      className="ct-flip-in"
                      style={{
                        fontFamily: 'var(--mantine-font-family-monospace)',
                        fontSize: 11,
                        fontWeight: 700,
                        color: tokens.codeInk,
                        background: 'rgba(0,0,0,0.28)',
                        borderRadius: 7,
                        padding: '2px 7px',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {code.code}
                    </Text>
                  )}
                  <Box
                    role="button"
                    aria-label="Remove tag"
                    onClick={() => removeEntry(tag.id)}
                    style={{
                      display: 'inline-flex',
                      cursor: 'pointer',
                      color: 'rgba(255,255,255,0.8)',
                    }}
                  >
                    <IconX size={14} />
                  </Box>
                </Group>
              );
            })}
          </Group>
        </Stack>
      )}
    </Box>
  );
}
