import { Box, Group, Text } from '@mantine/core';
import type { ReactNode } from 'react';
import { tokens } from '../theme';

// A "clinical chart" card used to group each field on a screen.
export function Panel({
  title,
  accent,
  children,
}: {
  title: string;
  accent?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Box
      style={{
        background: tokens.surface,
        border: `1px solid ${tokens.border}`,
        borderRadius: 20,
        boxShadow: 'var(--mantine-shadow-sm)',
        // NOTE: no `overflow: hidden` here — it would clip the type-ahead
        // dropdown (positioned just below the input) whenever the panel is
        // short. The header rounds its own top corners instead.
      }}
    >
      <Group
        justify="space-between"
        px="lg"
        py="sm"
        style={{
          borderBottom: `1px solid ${tokens.canvas}`,
          background: 'linear-gradient(180deg, #fbfdfe, #f4f8fa)',
          borderTopLeftRadius: 20,
          borderTopRightRadius: 20,
        }}
      >
        <Text fw={700} ff="Fraunces, serif" fz="md" style={{ color: tokens.ink }}>
          {title}
        </Text>
        {accent}
      </Group>
      <Box p="lg">{children}</Box>
    </Box>
  );
}
