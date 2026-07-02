import { Box, Group, Loader, Text } from '@mantine/core';
import { IconPlus, IconSparkles } from '@tabler/icons-react';
import type { SearchErrorKind, Suggestion } from '../types';

interface ChipRailProps {
  suggestions: Suggestion[];
  loading: boolean;
  error: { kind: SearchErrorKind; message: string } | null;
  hasQuery: boolean;
  showCodes: boolean;
  onTap: (s: Suggestion) => void;
}

// The note field's semantic rail: tappable SNOMED concept chips surfaced by
// meaning as the clinician writes. Tapping a chip commits a coded tag.
export function ChipRail({
  suggestions,
  loading,
  error,
  hasQuery,
  showCodes,
  onTap,
}: ChipRailProps) {
  if (!hasQuery) return null;

  if (error) {
    return (
      <Text size="xs" c="coral.7" mt={8}>
        {error.message}
      </Text>
    );
  }

  if (loading && suggestions.length === 0) {
    return (
      <Group gap={8} mt={10}>
        <Loader size="xs" color="teal" />
        <Text size="xs" c="slate.6">
          Reading the note semantically…
        </Text>
      </Group>
    );
  }

  if (suggestions.length === 0) return null;

  return (
    <Box mt={10}>
      <Group gap={6} mb={6} align="center">
        <IconSparkles size={13} color="var(--mantine-color-teal-7)" />
        <Text className="ct-eyebrow" c="teal.8" style={{ letterSpacing: '0.12em' }}>
          Suggested concepts
        </Text>
      </Group>
      <Group gap={8}>
        {suggestions.map((s, i) => {
          const code = s.codes[0]?.code;
          return (
            <Box
              key={s.id}
              className="ct-chip-in"
              role="button"
              tabIndex={0}
              onClick={() => onTap(s)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onTap(s);
                }
              }}
              style={{
                animationDelay: `${i * 40}ms`,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                cursor: 'pointer',
                padding: '6px 10px 6px 8px',
                borderRadius: 999,
                border: '1px solid var(--mantine-color-teal-2)',
                background: 'var(--mantine-color-teal-0)',
                transition: 'transform 120ms ease, box-shadow 120ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'translateY(-1px)';
                e.currentTarget.style.boxShadow = 'var(--mantine-shadow-sm)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.boxShadow = 'none';
              }}
            >
              <IconPlus size={13} color="var(--mantine-color-teal-7)" />
              <Text size="sm" fw={600} c="teal.9">
                {s.label}
              </Text>
              {showCodes && code && (
                <Text
                  span
                  style={{
                    fontFamily: 'var(--mantine-font-family-monospace)',
                    fontSize: 11,
                    fontWeight: 700,
                    color: 'var(--mantine-color-teal-7)',
                  }}
                >
                  {code}
                </Text>
              )}
            </Box>
          );
        })}
      </Group>
    </Box>
  );
}
