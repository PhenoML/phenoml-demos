import {
  Badge,
  Box,
  Group,
  SegmentedControl,
  Switch,
  Text,
  Tooltip,
} from '@mantine/core';
import { IconCode, IconStethoscope } from '@tabler/icons-react';
import { useAppState } from '../hooks/useAppState';
import { tokens } from '../theme';

export type Screen = 'encounter' | 'orders';

export function TopBar({
  screen,
  onChangeScreen,
}: {
  screen: Screen;
  onChangeScreen: (s: Screen) => void;
}) {
  const { demoMode, setDemoMode, showCodes, setShowCodes, liveAvailable } =
    useAppState();
  const liveReady = liveAvailable;

  return (
    <Box
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        background: 'rgba(255,255,255,0.82)',
        backdropFilter: 'blur(12px)',
        borderBottom: `1px solid ${tokens.border}`,
      }}
    >
      <Group
        justify="space-between"
        wrap="nowrap"
        px="xl"
        py="sm"
        style={{ maxWidth: 1120, margin: '0 auto' }}
      >
        {/* Brand */}
        <Group gap={12} wrap="nowrap">
          <Box
            style={{
              width: 38,
              height: 38,
              borderRadius: 12,
              background: 'linear-gradient(135deg, var(--mantine-color-teal-6), var(--mantine-color-teal-9))',
              display: 'grid',
              placeItems: 'center',
              boxShadow: 'var(--mantine-shadow-sm)',
            }}
          >
            <IconStethoscope size={21} color="white" />
          </Box>
          <Box>
            <Text
              fw={700}
              ff="Fraunces, serif"
              fz="lg"
              lh={1.1}
              style={{ color: tokens.ink }}
            >
              Construe Type-Ahead
            </Text>
            <Text size="xs" c="slate.6" lh={1.1}>
              Plain language in · coded concepts out
            </Text>
          </Box>
        </Group>

        {/* Screen switch */}
        <SegmentedControl
          value={screen}
          onChange={(v) => onChangeScreen(v as Screen)}
          radius="lg"
          color="teal"
          data={[
            { label: 'Encounter note', value: 'encounter' },
            { label: 'Orders', value: 'orders' },
          ]}
        />

        {/* Controls */}
        <Group gap="md" wrap="nowrap">
          <Tooltip
            label={
              liveReady
                ? 'Live calls the Construe API through the local proxy'
                : 'Set PhenoML credentials in .env to enable Live mode'
            }
            withArrow
          >
            <SegmentedControl
              value={demoMode ? 'demo' : 'live'}
              onChange={(v) => setDemoMode(v === 'demo')}
              radius="lg"
              size="sm"
              color={demoMode ? 'teal' : 'coral'}
              data={[
                { label: 'Demo', value: 'demo' },
                { label: 'Live', value: 'live' },
              ]}
            />
          </Tooltip>

          <Switch
            checked={showCodes}
            onChange={(e) => setShowCodes(e.currentTarget.checked)}
            color="teal"
            size="md"
            thumbIcon={
              showCodes ? <IconCode size={12} color="var(--mantine-color-teal-7)" /> : undefined
            }
            label={
              <Text size="sm" fw={600} c="slate.8">
                Show codes
              </Text>
            }
          />

          {!demoMode && (
            <Badge color={liveReady ? 'teal' : 'coral'} variant="light" radius="sm">
              {liveReady ? 'Live' : 'No creds'}
            </Badge>
          )}
        </Group>
      </Group>
    </Box>
  );
}
