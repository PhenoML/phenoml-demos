// Shared presentational bits used by both the Provider and Payer views.
import {
  Card, Text, Badge, Group, Stack, List, ThemeIcon, Table, Code, Spoiler, Divider,
} from "@mantine/core";
import { IconCheck, IconAlertCircle } from "@tabler/icons-react";
import type { Readiness } from "./api";

function value(r: any): string {
  const vcc = r.valueCodeableConcept;
  if (vcc?.text) return vcc.text;
  if (r.valueString) return r.valueString;
  if (r.valueQuantity) return `${r.valueQuantity.value ?? ""} ${r.valueQuantity.unit ?? ""}`.trim();
  return "";
}
function label(r: any): string {
  return r.code?.text || r.code?.coding?.[0]?.display || r.resourceType;
}

export function ReadinessPanel({ readiness }: { readiness: Readiness }) {
  return (
    <Card withBorder radius="md" padding="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Readiness gap-check</Text>
        {readiness.missing.length === 0
          ? <Badge color="teal">Ready to submit</Badge>
          : <Badge color="orange">{readiness.missing.length} element(s) missing</Badge>}
      </Group>
      <Text size="sm" c="dimmed" mb="xs">
        Same DataRequirement check the payer runs — run on the provider side, before submitting.
      </Text>
      <Group align="flex-start" grow>
        <div>
          <Text size="sm" fw={500} mb={4}>On file</Text>
          <List spacing={2} size="sm" icon={
            <ThemeIcon color="teal" size={16} radius="xl"><IconCheck size={11} /></ThemeIcon>}>
            {readiness.satisfied.map((s) => <List.Item key={s.label}>{s.label}</List.Item>)}
          </List>
        </div>
        <div>
          <Text size="sm" fw={500} mb={4}>Missing / unresolved</Text>
          {readiness.missing.length === 0
            ? <Text size="sm" c="dimmed">none</Text>
            : <List spacing={2} size="sm" icon={
                <ThemeIcon color="orange" size={16} radius="xl"><IconAlertCircle size={11} /></ThemeIcon>}>
                {readiness.missing.map((m) => <List.Item key={m.label}>{m.label}</List.Item>)}
              </List>}
        </div>
      </Group>
      {readiness.follow_up_questions.length > 0 && (
        <>
          <Divider my="sm" />
          <Text size="sm" fw={500} mb={4}>Readiness agent — follow-up</Text>
          <List size="sm" spacing={2}>
            {readiness.follow_up_questions.map((q, i) => <List.Item key={i}>{q}</List.Item>)}
          </List>
        </>
      )}
    </Card>
  );
}

export function EvidencePanel({ resources, construeCodes, ips, regimen }: {
  resources: any[]; construeCodes: Record<string, any[]>; ips: string; regimen: any;
}) {
  const codeRows = Object.entries(construeCodes || {})
    .filter(([k]) => k !== "_errors")
    .flatMap(([sys, codes]) => (codes || []).map((c: any) => ({ sys, ...c })));

  return (
    <Stack gap="md">
      <Card withBorder radius="md" padding="md">
        <Text fw={600} mb="xs">Regimen</Text>
        <Text size="sm">{regimen?.code?.text || "TH (paclitaxel + trastuzumab)"}</Text>
        <Text size="xs" c="dimmed" mt={4}>
          {(regimen?.extension || []).map((e: any) => e.valueCodeableConcept?.text).filter(Boolean).join(" · ")}
        </Text>
      </Card>

      <Card withBorder radius="md" padding="md">
        <Text fw={600} mb="xs">Structured evidence (mCODE)</Text>
        <Table striped withRowBorders={false} verticalSpacing={4}>
          <Table.Tbody>
            {resources.map((r, i) => (
              <Table.Tr key={i}>
                <Table.Td><Badge variant="light" size="sm">{r.resourceType}</Badge></Table.Td>
                <Table.Td>{label(r)}</Table.Td>
                <Table.Td><Text fw={500}>{value(r)}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      {codeRows.length > 0 && (
        <Card withBorder radius="md" padding="md">
          <Text fw={600} mb="xs">Validated codes (with citations)</Text>
          <Table verticalSpacing={4}>
            <Table.Thead>
              <Table.Tr><Table.Th>System</Table.Th><Table.Th>Code</Table.Th>
                <Table.Th>Description</Table.Th><Table.Th>Citation</Table.Th></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {codeRows.map((c: any, i: number) => (
                <Table.Tr key={i}>
                  <Table.Td><Code>{c.sys}</Code></Table.Td>
                  <Table.Td><Code>{c.code}</Code></Table.Td>
                  <Table.Td>{c.description}</Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{c.citations?.[0]?.text || ""}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      {ips && (
        <Card withBorder radius="md" padding="md">
          <Text fw={600} mb="xs">International Patient Summary</Text>
          <Spoiler maxHeight={140} showLabel="Show full summary" hideLabel="Hide">
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{ips}</Text>
          </Spoiler>
        </Card>
      )}
    </Stack>
  );
}
