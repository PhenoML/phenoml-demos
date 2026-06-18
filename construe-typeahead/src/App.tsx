import { useState } from 'react';
import { Badge, Box, Group, Stack, Text } from '@mantine/core';
import { IconBulb, IconEyeOff } from '@tabler/icons-react';
import { useDisclosure } from '@mantine/hooks';
import { TopBar, type Screen } from './components/TopBar';
import { SettingsPanel } from './components/SettingsPanel';
import { EncounterScreen } from './screens/EncounterScreen';
import { OrdersScreen } from './screens/OrdersScreen';
import { useAppState } from './hooks/useAppState';
import { tokens } from './theme';

export default function App() {
  const [screen, setScreen] = useState<Screen>('encounter');
  const [settingsOpened, settings] = useDisclosure(false);
  const { demoMode, showCodes, entries } = useAppState();

  return (
    <Box>
      <TopBar
        screen={screen}
        onChangeScreen={setScreen}
        onOpenSettings={settings.open}
      />

      <Box
        style={{
          maxWidth: 1120,
          margin: '0 auto',
          padding: '28px 24px 96px',
        }}
      >
        {/* Hero / framing line */}
        <Stack gap={6} mb="lg">
          <Group gap={10} align="center">
            <Text
              ff="Fraunces, serif"
              fw={600}
              style={{
                fontSize: 30,
                lineHeight: 1.1,
                color: tokens.ink,
                letterSpacing: '-0.01em',
              }}
            >
              {screen === 'encounter' ? 'Encounter note' : 'Orders'}
            </Text>
            <Badge
              variant="light"
              color={demoMode ? 'teal' : 'coral'}
              radius="sm"
              size="lg"
            >
              {demoMode ? 'Demo Mode' : 'Live'}
            </Badge>
          </Group>
          <Text size="sm" c="slate.7" maw={680}>
            The clinician types in plain language; the app silently stores
            structured medical codes. Toggle{' '}
            <Text span fw={700} c="teal.8">
              Show codes
            </Text>{' '}
            to reveal exactly what was captured.
          </Text>
        </Stack>

        {/* Demo cheat-sheet */}
        {demoMode && (
          <Group
            gap={10}
            mb="lg"
            p="sm"
            wrap="wrap"
            style={{
              background: 'var(--mantine-color-teal-0)',
              border: '1px solid var(--mantine-color-teal-2)',
              borderRadius: 12,
            }}
          >
            <Group gap={6}>
              <IconBulb size={15} color="var(--mantine-color-teal-8)" />
              <Text className="ct-eyebrow" c="teal.8">
                Try
              </Text>
            </Group>
            {(screen === 'encounter'
              ? ['asth → Asthma', 'albut → Albuterol', 'shortness of breath (note)']
              : ['lipid panel', 'a1c', 'creatinine']
            ).map((t) => (
              <Badge key={t} variant="white" color="teal" radius="sm" tt="none">
                {t}
              </Badge>
            ))}
          </Group>
        )}

        {/* Active screen */}
        {screen === 'encounter' ? <EncounterScreen /> : <OrdersScreen />}

        {/* Footer status */}
        <Group gap={8} mt="xl" justify="center">
          {!showCodes && entries.length > 0 && (
            <Group gap={6}>
              <IconEyeOff size={14} color="var(--mantine-color-slate-6)" />
              <Text size="xs" c="slate.6">
                {entries.length} coded {entries.length === 1 ? 'concept' : 'concepts'} stored
                silently — flip “Show codes” to reveal them.
              </Text>
            </Group>
          )}
        </Group>
      </Box>

      <SettingsPanel opened={settingsOpened} onClose={settings.close} />
    </Box>
  );
}
