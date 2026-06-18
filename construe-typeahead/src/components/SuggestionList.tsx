import { Box, Group, Loader, Text } from '@mantine/core';
import { IconAlertTriangle, IconSearch } from '@tabler/icons-react';
import type { SearchErrorKind, Suggestion } from '../types';
import { tokens } from '../theme';

interface SuggestionListProps {
  suggestions: Suggestion[];
  activeIndex: number;
  loading: boolean;
  error: { kind: SearchErrorKind; message: string } | null;
  query: string;
  showCodes: boolean;
  onHover: (index: number) => void;
  onSelect: (s: Suggestion) => void;
}

const panelStyle: React.CSSProperties = {
  position: 'absolute',
  top: 'calc(100% + 8px)',
  left: 0,
  right: 0,
  zIndex: 40,
  background: tokens.surface,
  border: `1px solid ${tokens.border}`,
  borderRadius: 14,
  boxShadow: 'var(--mantine-shadow-lg)',
  overflow: 'hidden',
};

export function SuggestionList({
  suggestions,
  activeIndex,
  loading,
  error,
  query,
  showCodes,
  onHover,
  onSelect,
}: SuggestionListProps) {
  if (query.trim().length < 2) return null;

  if (error) {
    return (
      <Box style={panelStyle} className="ct-pop-in">
        <Group gap={10} p="md" wrap="nowrap" align="flex-start">
          <IconAlertTriangle size={18} color="var(--mantine-color-coral-6)" />
          <Box>
            <Text size="sm" fw={600} c="coral.8">
              {errorTitle(error.kind)}
            </Text>
            <Text size="xs" c="slate.7" mt={2}>
              {error.message}
            </Text>
          </Box>
        </Group>
      </Box>
    );
  }

  if (loading && suggestions.length === 0) {
    return (
      <Box style={panelStyle} className="ct-pop-in">
        <Group gap={10} p="md">
          <Loader size="xs" color="teal" />
          <Text size="sm" c="slate.7">
            Searching Construe…
          </Text>
        </Group>
      </Box>
    );
  }

  if (suggestions.length === 0) {
    return (
      <Box style={panelStyle} className="ct-pop-in">
        <Group gap={10} p="md">
          <IconSearch size={16} color="var(--mantine-color-slate-5)" />
          <Text size="sm" c="slate.7">
            No matching concepts for “{query.trim()}”.
          </Text>
        </Group>
      </Box>
    );
  }

  return (
    <Box style={panelStyle} className="ct-pop-in" role="listbox">
      {suggestions.map((s, i) => {
        const active = i === activeIndex;
        const primary = s.codes[0];
        return (
          <Group
            key={s.id}
            role="option"
            aria-selected={active}
            justify="space-between"
            wrap="nowrap"
            gap={12}
            px="md"
            py={10}
            onMouseEnter={() => onHover(i)}
            onMouseDown={(e) => {
              // mousedown (not click) so we commit before the input blurs.
              e.preventDefault();
              onSelect(s);
            }}
            style={{
              cursor: 'pointer',
              background: active ? 'var(--mantine-color-teal-0)' : 'transparent',
              borderLeft: `3px solid ${
                active ? 'var(--mantine-color-teal-6)' : 'transparent'
              }`,
              borderBottom: i === suggestions.length - 1 ? 'none' : `1px solid ${tokens.canvas}`,
            }}
          >
            <Text size="sm" fw={active ? 600 : 500} style={{ color: tokens.ink }}>
              {s.label}
            </Text>
            {showCodes && primary && (
              <Text
                span
                style={{
                  fontFamily: 'var(--mantine-font-family-monospace)',
                  fontSize: 11.5,
                  fontWeight: 700,
                  color: 'var(--mantine-color-teal-8)',
                  background: 'var(--mantine-color-teal-0)',
                  border: '1px solid var(--mantine-color-teal-2)',
                  borderRadius: 7,
                  padding: '2px 7px',
                  whiteSpace: 'nowrap',
                }}
              >
                {primary.code}
              </Text>
            )}
          </Group>
        );
      })}
    </Box>
  );
}

function errorTitle(kind: SearchErrorKind): string {
  switch (kind) {
    case 'auth':
      return 'Authentication failed';
    case 'not_found':
      return 'Code system not found';
    case 'not_configured':
      return 'Search not configured';
    case 'network':
      return 'Could not reach Construe';
    default:
      return 'Search error';
  }
}
