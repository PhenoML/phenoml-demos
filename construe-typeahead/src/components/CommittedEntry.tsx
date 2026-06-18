import { ActionIcon, Box, Group, Stack, Text } from '@mantine/core';
import { IconX } from '@tabler/icons-react';
import type { CommittedEntry as Entry } from '../types';
import { useAppState } from '../hooks/useAppState';
import { CodeBadge } from './CodeBadge';
import { tokens } from '../theme';

// One committed item: the human-readable text the clinician sees, plus the
// stored codes revealed when "Show codes" is on (the key sales moment).
export function CommittedEntry({ entry }: { entry: Entry }) {
  const { showCodes, removeEntry } = useAppState();

  return (
    <Box
      style={{
        background: tokens.surface,
        border: `1px solid ${tokens.border}`,
        borderRadius: 14,
        padding: '12px 14px',
        boxShadow: 'var(--mantine-shadow-xs)',
      }}
    >
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Group gap={10} wrap="nowrap" align="center" style={{ flex: 1, minWidth: 0 }}>
          <Box
            style={{
              width: 8,
              height: 8,
              borderRadius: 8,
              background: 'var(--mantine-color-teal-6)',
              flexShrink: 0,
            }}
          />
          <Text fw={600} size="sm" style={{ color: tokens.ink }}>
            {entry.text}
          </Text>
        </Group>
        <ActionIcon
          variant="subtle"
          color="slate"
          size="sm"
          aria-label="Remove"
          onClick={() => removeEntry(entry.id)}
        >
          <IconX size={15} />
        </ActionIcon>
      </Group>

      {showCodes && entry.codes.length > 0 && (
        <Stack gap={6} mt={10} className="ct-flip-in">
          {entry.codes.map((c) => (
            <CodeBadge key={`${c.system}:${c.code}`} concept={c} />
          ))}
        </Stack>
      )}
    </Box>
  );
}
