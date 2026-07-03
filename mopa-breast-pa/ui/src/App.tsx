import { useEffect, useState } from "react";
import {
  AppShell, Group, Title, Tabs, Alert, Badge, Container, Text,
} from "@mantine/core";
import { IconStethoscope, IconShieldCheck, IconAlertTriangle } from "@tabler/icons-react";
import { api } from "./api";
import { ProviderView } from "./ProviderView";
import { PayerView } from "./PayerView";

export function App() {
  const [tab, setTab] = useState<string>("provider");
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [queueBump, setQueueBump] = useState(0); // incremented on submit to refresh the payer queue

  useEffect(() => {
    api.health().then((h) => { setConfigured(h.configured); setProvider(h.provider); })
      .catch(() => setConfigured(false));
  }, []);

  return (
    <AppShell header={{ height: 60 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Title order={4}>MOPA Prior-Auth</Title>
            <Text c="dimmed" size="sm">breast-cancer oncology · OncoHealth UM-9 · Medplum EHR</Text>
          </Group>
          {configured === true && <Badge color="teal" variant="light">PhenoML connected</Badge>}
          {configured === false && <Badge color="red" variant="light">not configured</Badge>}
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="lg">
          {configured === false && (
            <Alert color="orange" icon={<IconAlertTriangle size={18} />} mb="md"
              title="Backend not connected to PhenoML">
              Set <code>PHENOML_CLIENT_ID</code>, <code>PHENOML_CLIENT_SECRET</code> and{" "}
              <code>PHENOML_FHIR_PROVIDER_ID</code>, then restart <code>ui_server.py</code>.
            </Alert>
          )}

          <Tabs value={tab} onChange={(v) => setTab(v || "provider")}>
            <Tabs.List mb="md">
              <Tabs.Tab value="provider" leftSection={<IconStethoscope size={16} />}>
                Provider — submit
              </Tabs.Tab>
              <Tabs.Tab value="payer" leftSection={<IconShieldCheck size={16} />}>
                Payer — review
              </Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="provider">
              <ProviderView
                onSubmitted={() => { setQueueBump((n) => n + 1); setTab("payer"); }}
              />
            </Tabs.Panel>
            <Tabs.Panel value="payer">
              <PayerView refreshKey={queueBump} />
            </Tabs.Panel>
          </Tabs>

          {provider && (
            <Text c="dimmed" size="xs" mt="xl">FHIR provider: {provider}</Text>
          )}
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
