import { useEffect, useState } from "react";
import {
  Button, Textarea, Card, Group, Stack, Text, Loader, Alert, Badge, Grid,
  Switch, TextInput, Divider,
} from "@mantine/core";
import { IconUpload, IconSend, IconFileText } from "@tabler/icons-react";
import { api, type IntakeResult } from "./api";
import { ReadinessPanel, EvidencePanel } from "./components";

const DEFAULT_HER2 =
  "HER2 status by reflex in-situ hybridization (ISH): POSITIVE (HER2 gene amplified). " +
  "Resolves the earlier equivocal IHC 2+ result.";

export function ProviderView({ onSubmitted }: { onSubmitted: () => void }) {
  const [report, setReport] = useState("");
  const [intake, setIntake] = useState<IntakeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [her2Text, setHer2Text] = useState(DEFAULT_HER2);
  const [her2Positive, setHer2Positive] = useState(true);

  useEffect(() => { api.sampleReport().then((r) => setReport(r.report_text)).catch(() => {}); }, []);

  async function runIntake() {
    setBusy(true); setErr(null); setIntake(null); setSubmitted(false);
    try { setIntake(await api.intake(report)); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!intake || submitting || submitted) return;
    setSubmitting(true); setErr(null);
    try {
      await api.submit(intake.intake_id, her2Text, her2Positive);
      setSubmitted(true);
      onSubmitted();
    } catch (e: any) { setErr(e.message); }
    finally { setSubmitting(false); }
  }

  return (
    <Stack gap="md">
      <Card withBorder radius="md" padding="md">
        <Group justify="space-between" mb="xs">
          <Text fw={600}><IconFileText size={16} style={{ verticalAlign: "-2px" }} /> Pathology report</Text>
          <Badge variant="light" color="gray">prefilled: Jane Smith (HER2 equivocal)</Badge>
        </Group>
        <Textarea value={report} onChange={(e) => setReport(e.currentTarget.value)}
          autosize minRows={6} maxRows={14} />
        <Group mt="sm">
          <Button leftSection={<IconUpload size={16} />} onClick={runIntake} loading={busy}>
            Run intake
          </Button>
          <Text size="sm" c="dimmed">lang2fhir → construe → RequestGroup → IPS → readiness gap-check</Text>
        </Group>
      </Card>

      {err && <Alert color="red" title="Error">{err}</Alert>}
      {busy && <Group><Loader size="sm" /><Text>Extracting FHIR, validating codes, generating IPS…</Text></Group>}

      {intake && (
        <>
          <Group>
            <Text fw={600}>Patient:</Text><Text>{intake.patient_name}</Text>
            {intake.write.ok
              ? <Badge color="teal" variant="light">
                  chart written to EHR{intake.patient_id ? ` · Patient/${intake.patient_id}` : ""}</Badge>
              : <Badge color="gray" variant="light">read-only instance — chart held in memory</Badge>}
          </Group>

          <Grid>
            <Grid.Col span={{ base: 12, md: 7 }}>
              <EvidencePanel resources={intake.resources} construeCodes={intake.construe_codes}
                ips={intake.ips_text} regimen={intake.regimen} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 5 }}>
              <Stack gap="md">
                <ReadinessPanel readiness={intake.readiness} />
                <Card withBorder radius="md" padding="md">
                  <Text fw={600} mb="xs">Resolve HER2 &amp; submit</Text>
                  <Text size="sm" c="dimmed" mb="xs">
                    The reflex ISH result closes the gap. This is written back to the EHR, then a
                    preauthorization Claim is submitted for payer review.
                  </Text>
                  <TextInput label="HER2 result (as reported)" value={her2Text}
                    onChange={(e) => setHer2Text(e.currentTarget.value)} mb="xs" />
                  <Switch label={her2Positive ? "HER2 POSITIVE (amplified)" : "HER2 NEGATIVE"}
                    checked={her2Positive} onChange={(e) => setHer2Positive(e.currentTarget.checked)}
                    mb="sm" />
                  <Divider mb="sm" />
                  <Button fullWidth color="teal" leftSection={<IconSend size={16} />}
                    onClick={submit} loading={submitting} disabled={submitted}>
                    {submitted ? "Submitted" : "Submit prior authorization"}
                  </Button>
                </Card>
              </Stack>
            </Grid.Col>
          </Grid>
        </>
      )}
    </Stack>
  );
}
