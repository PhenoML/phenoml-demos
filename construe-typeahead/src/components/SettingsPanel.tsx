import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { IconShieldLock } from '@tabler/icons-react';
import { useAppState } from '../hooks/useAppState';
import type { Settings } from '../types';

// Collects clientId / clientSecret / baseUrl. baseUrl is editable so the
// instance host can be swapped (we run multiple instances). Values are seeded
// from .env when present. Includes the mandatory browser-secret warning.
export function SettingsPanel({
  opened,
  onClose,
}: {
  opened: boolean;
  onClose: () => void;
}) {
  const { settings, updateSettings } = useAppState();
  const [form, setForm] = useState<Settings>(settings);

  // Re-sync the form whenever the panel reopens.
  useEffect(() => {
    if (opened) setForm(settings);
  }, [opened, settings]);

  function save() {
    updateSettings({
      clientId: form.clientId.trim(),
      clientSecret: form.clientSecret.trim(),
      baseUrl: form.baseUrl.trim() || settings.baseUrl,
    });
    onClose();
  }

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Text fw={700} ff="Fraunces, serif" fz="lg">
          Construe connection
        </Text>
      }
      radius="lg"
      size="lg"
      centered
    >
      <Stack gap="md">
        <Alert
          variant="light"
          color="coral"
          icon={<IconShieldLock size={18} />}
          radius="md"
        >
          <Text size="sm" fw={600} mb={2}>
            Internal / dev use only
          </Text>
          <Text size="xs">
            In Live mode the client secret is sent straight from the browser. Do
            not paste production credentials, and never share a public link that
            bakes these in. For demos, leave Demo Mode on — it needs no creds.
          </Text>
        </Alert>

        <TextInput
          label="Instance base URL"
          description="Swap this to point at a different Construe instance."
          value={form.baseUrl}
          onChange={(e) => setForm({ ...form, baseUrl: e.currentTarget.value })}
          placeholder="https://experiment.app.pheno.ml"
          radius="md"
        />
        <TextInput
          label="Client ID"
          value={form.clientId}
          onChange={(e) => setForm({ ...form, clientId: e.currentTarget.value })}
          placeholder="client_id"
          radius="md"
        />
        <PasswordInput
          label="Client secret"
          value={form.clientSecret}
          onChange={(e) => setForm({ ...form, clientSecret: e.currentTarget.value })}
          placeholder="client_secret"
          radius="md"
        />

        <Text size="xs" c="slate.6">
          Tip: set <code>VITE_PHENOML_CLIENT_ID</code>,{' '}
          <code>VITE_PHENOML_CLIENT_SECRET</code> and{' '}
          <code>VITE_PHENOML_BASE_URL</code> in a <code>.env</code> file to
          pre-fill these.
        </Text>

        <Group justify="flex-end" mt={4}>
          <Button variant="subtle" color="slate" onClick={onClose}>
            Cancel
          </Button>
          <Button color="teal" onClick={save}>
            Save connection
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
