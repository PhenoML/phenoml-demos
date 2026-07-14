import { useCallback, useEffect, useState } from "react";
import {
  Card, Table, Badge, Button, Group, Stack, Text, Loader, Alert, Grid, Title,
  SegmentedControl, Textarea, Divider, Anchor,
} from "@mantine/core";
import { IconRefresh, IconGavel, IconThumbUp, IconThumbDown, IconRobot } from "@tabler/icons-react";
import { api, type ClaimRecord, type ClaimDetail, type Recommendation } from "./api";
import { ReadinessPanel, EvidencePanel } from "./components";

const STATUS_COLOR: Record<string, string> = { queued: "blue", approved: "teal", denied: "red" };
const INDICATOR_COLOR: Record<string, string> = { info: "teal", warning: "orange", critical: "red" };

export function PayerView({ refreshKey }: { refreshKey: number }) {
  const [claims, setClaims] = useState<ClaimRecord[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<ClaimDetail | null>(null);
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [her2, setHer2] = useState("resolved");
  const [note, setNote] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [loadingRec, setLoadingRec] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadList = useCallback(() => {
    setLoadingList(true);
    api.claims().then((r) => setClaims(r.claims)).catch((e) => setErr(e.message))
      .finally(() => setLoadingList(false));
  }, []);

  useEffect(() => { loadList(); }, [loadList, refreshKey]);

  async function open(id: string) {
    setSel(id); setDetail(null); setRec(null); setNote(""); setHer2("resolved"); setErr(null);
    try { setDetail(await api.claim(id)); } catch (e: any) { setErr(e.message); }
  }

  async function recommend() {
    if (!sel) return;
    setLoadingRec(true); setErr(null); setRec(null);
    try {
      const r = await api.recommend(sel, her2 === "resolved" ? null : her2);
      setRec(r);
      setNote(r.card?.detail || "");
    } catch (e: any) { setErr(e.message); }
    finally { setLoadingRec(false); }
  }

  async function decide(decision: "approve" | "deny") {
    if (!sel) return;
    setDeciding(true); setErr(null);
    try {
      await api.decide(sel, decision, note, [], decision === "approve" ? rec?.coverage : null);
      await open(sel);
      loadList();
    } catch (e: any) { setErr(e.message); }
    finally { setDeciding(false); }
  }

  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 4 }}>
        <Card withBorder radius="md" padding="md">
          <Group justify="space-between" mb="xs">
            <Text fw={600}>Review queue</Text>
            <Button size="xs" variant="light" leftSection={<IconRefresh size={14} />}
              onClick={loadList} loading={loadingList}>Refresh</Button>
          </Group>
          {claims.length === 0 && <Text size="sm" c="dimmed">No submissions yet.</Text>}
          <Table highlightOnHover verticalSpacing={6}>
            <Table.Tbody>
              {claims.map((c) => (
                <Table.Tr key={c.id} onClick={() => open(c.id)}
                  style={{ cursor: "pointer", background: sel === c.id ? "var(--mantine-color-blue-0)" : undefined }}>
                  <Table.Td>
                    <Text fw={500}>{c.patient_name}</Text>
                    <Text size="xs" c="dimmed">{c.regimen_text}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={STATUS_COLOR[c.status]} variant="light">{c.status}</Badge>
                    {!c.persisted && <Text size="10px" c="dimmed">local only</Text>}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      </Grid.Col>

      <Grid.Col span={{ base: 12, md: 8 }}>
        {err && <Alert color="red" title="Error" mb="md">{err}</Alert>}
        {!sel && <Text c="dimmed">Select a submission from the queue to review it.</Text>}
        {sel && !detail && <Group><Loader size="sm" /><Text>Loading…</Text></Group>}

        {detail && (
          <Stack gap="md">
            <Group justify="space-between">
              <Title order={4}>{detail.patient_name}</Title>
              <Badge color={STATUS_COLOR[detail.claim.status]} size="lg" variant="light">
                {detail.claim.status}</Badge>
            </Group>

            <Card withBorder radius="md" padding="md">
              <Group justify="space-between" mb="xs">
                <Text fw={600}><IconRobot size={16} style={{ verticalAlign: "-2px" }} /> OncoHealth UM-9 recommendation</Text>
                <Group gap="xs">
                  <Text size="xs" c="dimmed">HER2 what-if:</Text>
                  <SegmentedControl size="xs" value={her2} onChange={setHer2}
                    data={[{ label: "Resolved", value: "resolved" },
                           { label: "Positive", value: "positive" },
                           { label: "Negative", value: "negative" }]} />
                </Group>
              </Group>
              <Button size="sm" variant="light" leftSection={<IconGavel size={16} />}
                onClick={recommend} loading={loadingRec} mb="sm">
                Get recommendation
              </Button>

              {rec && (
                <Alert color={INDICATOR_COLOR[rec.card?.indicator || "info"]}
                  title={`${rec.decision} — ${rec.card?.summary || ""}`}>
                  <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{rec.card?.detail}</Text>
                  {rec.card?.links?.map((l, i) => (
                    <Anchor key={i} href={l.url} size="sm" target="_blank">{l.label}</Anchor>
                  ))}
                  <Text size="xs" c="dimmed" mt="xs">evidence used: HER2 {rec.her2_used}</Text>
                </Alert>
              )}

              {rec && (
                <>
                  <Divider my="sm" label="Decision (human-in-the-loop)" />
                  <Textarea label="Rationale / note (editable — you can override the AI)"
                    value={note} onChange={(e) => setNote(e.currentTarget.value)}
                    autosize minRows={2} maxRows={6} mb="sm" />
                  <Group>
                    <Button color="teal" leftSection={<IconThumbUp size={16} />}
                      onClick={() => decide("approve")} loading={deciding}>Approve</Button>
                    <Button color="red" variant="light" leftSection={<IconThumbDown size={16} />}
                      onClick={() => decide("deny")} loading={deciding}>Deny</Button>
                  </Group>
                </>
              )}

              {detail.decision && (
                <Alert mt="sm" color={detail.decision.decision === "approved" ? "teal" : "red"}
                  title={`Recorded: ${detail.decision.decision}`}>
                  <Text size="sm">{detail.decision.rationale}</Text>
                  {detail.decision.claim_response_id &&
                    <Text size="xs" c="dimmed" mt={4}>
                      ClaimResponse/{detail.decision.claim_response_id} written to EHR</Text>}
                </Alert>
              )}
            </Card>

            <ReadinessPanel readiness={detail.readiness} />
            <EvidencePanel resources={detail.resources} construeCodes={detail.construe_codes}
              ips={detail.ips_text} regimen={detail.regimen} />
          </Stack>
        )}
      </Grid.Col>
    </Grid>
  );
}
