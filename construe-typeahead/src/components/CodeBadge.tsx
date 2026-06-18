import { Box, Group, Text } from '@mantine/core';
import type { CodedConcept } from '../types';
import { tokens } from '../theme';

// A single stored coded concept, rendered with a deliberately "machine"
// treatment (dark slab + mono code) so structured data reads visually distinct
// from the human-readable text above it.
export function CodeBadge({ concept }: { concept: CodedConcept }) {
  return (
    <Box
      style={{
        background: tokens.codeBg,
        borderRadius: 10,
        padding: '6px 10px',
        border: '1px solid rgba(127, 232, 210, 0.18)',
      }}
    >
      <Group gap={8} wrap="nowrap" align="center">
        <Text
          span
          style={{
            fontFamily: 'var(--mantine-font-family-monospace)',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '0.04em',
            color: 'rgba(255,255,255,0.55)',
            whiteSpace: 'nowrap',
          }}
        >
          {concept.system}
        </Text>
        <Text
          span
          style={{
            fontFamily: 'var(--mantine-font-family-monospace)',
            fontSize: 13,
            fontWeight: 700,
            color: tokens.codeInk,
            whiteSpace: 'nowrap',
          }}
        >
          {concept.code}
        </Text>
        <Text
          span
          style={{
            fontSize: 12.5,
            color: 'rgba(255,255,255,0.82)',
            lineHeight: 1.3,
          }}
        >
          {concept.description}
        </Text>
      </Group>
    </Box>
  );
}
