import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  AppShell,
  Badge,
  Button,
  Card,
  Code,
  Container,
  Divider,
  Grid,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import {
  IconCloudUpload,
  IconDatabaseExport,
  IconFileAnalytics,
  IconHeartbeat,
  IconPackageExport,
  IconRefresh,
} from "@tabler/icons-react";
import { api, type ExtractResult, type Health, type ProfileInfo, type SourceData } from "./api";

const DEFAULT_HER2 =
  "HER2 status by reflex in-situ hybridization (ISH): POSITIVE (HER2 gene amplified). " +
  "Resolves the earlier equivocal IHC 2+ result.";

function resourceLabel(resource: any): string {
  return resource?.code?.text || resource?.code?.coding?.[0]?.display || resource?.resourceType || "";
}

function resourceValue(resource: any): string {
  if (resource?.valueCodeableConcept?.text) return resource.valueCodeableConcept.text;
  if (resource?.valueString) return resource.valueString;
  if (resource?.valueQuantity) {
    return `${resource.valueQuantity.value ?? ""} ${resource.valueQuantity.unit ?? ""}`.trim();
  }
  return "";
}

function JsonBlock({ value }: { value: any }) {
  return (
    <ScrollArea h={280} type="auto">
      <Code block>{JSON.stringify(value, null, 2)}</Code>
    </ScrollArea>
  );
}

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [source, setSource] = useState<SourceData | null>(null);
  const [profiles, setProfiles] = useState<ProfileInfo[]>([]);
  const [report, setReport] = useState("");
  const [includeHer2, setIncludeHer2] = useState(true);
  const [her2Positive, setHer2Positive] = useState(true);
  const [her2Text, setHer2Text] = useState(DEFAULT_HER2);
  const [extractResult, setExtractResult] = useState<ExtractResult | null>(null);
  const [summary, setSummary] = useState("");
  const [writeResult, setWriteResult] = useState<any | null>(null);
  const [uploadResult, setUploadResult] = useState<any | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    setError(null);
    try {
      const [h, s, p] = await Promise.all([api.health(), api.sourceData(), api.profiles()]);
      setHealth(h);
      setSource(s);
      setProfiles(p.profiles);
      setReport(s.report_text);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function runExtract() {
    setBusy("extract");
    setError(null);
    setSummary("");
    setWriteResult(null);
    setExtractResult(null);
    try {
      setExtractResult(await api.extract(report, includeHer2, her2Text, her2Positive));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function runSummary() {
    if (!extractResult) return;
    setBusy("summary");
    setError(null);
    try {
      const result = await api.summary(extractResult.extraction_id);
      setSummary(result.summary);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function writeBundle() {
    if (!extractResult) return;
    setBusy("write");
    setError(null);
    setWriteResult(null);
    try {
      setWriteResult(await api.writeBundle(extractResult.extraction_id));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function uploadProfiles() {
    setBusy("profiles");
    setError(null);
    setUploadResult(null);
    try {
      setUploadResult(await api.uploadProfiles());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  const resourceCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const resource of extractResult?.resources || []) {
      counts[resource.resourceType] = (counts[resource.resourceType] || 0) + 1;
    }
    return counts;
  }, [extractResult]);

  return (
    <AppShell header={{ height: 62 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <IconHeartbeat size={22} />
            <div>
              <Title order={4}>MOPA Lang2FHIR</Title>
              <Text size="xs" c="dimmed">Breast oncology data selection, Bundle write, and FHIR2Summary</Text>
            </div>
          </Group>
          <Group gap="xs">
            {health?.configured
              ? <Badge color="teal" variant="light">PhenoML connected</Badge>
              : <Badge color="red" variant="light">not configured</Badge>}
            {health?.fhir_provider_id
              ? <Badge color="blue" variant="light">FHIR Provider {health.fhir_provider_id}</Badge>
              : <Badge color="orange" variant="light">no FHIR Provider</Badge>}
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="xl">
          <Stack gap="md">
            {error && <Alert color="red" title="Error">{error}</Alert>}

            <Grid>
              <Grid.Col span={{ base: 12, lg: 4 }}>
                <Stack gap="md">
                  <Card withBorder radius="sm" padding="md">
                    <Group justify="space-between" mb="xs">
                      <Text fw={600}>Source data</Text>
                      <Button size="xs" variant="subtle" leftSection={<IconRefresh size={14} />} onClick={refresh}>
                        Refresh
                      </Button>
                    </Group>
                    <Table verticalSpacing={4}>
                      <Table.Tbody>
                        {(source?.artifacts || []).map((item) => (
                          <Table.Tr key={item.name}>
                            <Table.Td><Badge color={item.used ? "teal" : "gray"}>{item.used ? "used" : "not used"}</Badge></Table.Td>
                            <Table.Td>
                              <Text size="sm" fw={500}>{item.name}</Text>
                              <Text size="xs" c="dimmed">{item.use}</Text>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Card>

                  <Card withBorder radius="sm" padding="md">
                    <Text fw={600} mb="xs">OncoHealth data map</Text>
                    <Table verticalSpacing={4}>
                      <Table.Tbody>
                        {(source?.mapped_requirements || []).map((item) => (
                          <Table.Tr key={`${item.type}-${item.code || item.label}`}>
                            <Table.Td><Badge variant="light">{item.type}</Badge></Table.Td>
                            <Table.Td>
                              <Text size="sm">{item.label}</Text>
                              <Text size="xs" c="dimmed">{item.source}{item.code ? ` · ${item.code}` : ""}</Text>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Card>

                  <Card withBorder radius="sm" padding="md">
                    <Group justify="space-between" mb="xs">
                      <Text fw={600}>Profiles</Text>
                      <Button
                        size="xs"
                        variant="light"
                        leftSection={<IconCloudUpload size={14} />}
                        loading={busy === "profiles"}
                        onClick={uploadProfiles}
                      >
                        Upload
                      </Button>
                    </Group>
                    <Stack gap={6}>
                      {profiles.map((profile) => (
                        <Group key={profile.file} justify="space-between" gap="xs">
                          <Text size="sm">{profile.name || profile.file}</Text>
                          <Badge color={profile.valid ? "teal" : "red"} variant="light">
                            {profile.type || "invalid"}
                          </Badge>
                        </Group>
                      ))}
                    </Stack>
                    {uploadResult && (
                      <>
                        <Divider my="sm" />
                        <JsonBlock value={uploadResult} />
                      </>
                    )}
                  </Card>
                </Stack>
              </Grid.Col>

              <Grid.Col span={{ base: 12, lg: 8 }}>
                <Stack gap="md">
                  <Card withBorder radius="sm" padding="md">
                    <Group justify="space-between" mb="xs">
                      <Text fw={600}>Lang2FHIR input</Text>
                      <Group gap="xs">
                        <Switch
                          checked={includeHer2}
                          onChange={(event) => setIncludeHer2(event.currentTarget.checked)}
                          label="Include resolved HER2"
                        />
                        <Switch
                          checked={her2Positive}
                          onChange={(event) => setHer2Positive(event.currentTarget.checked)}
                          label={her2Positive ? "HER2 positive" : "HER2 negative"}
                        />
                      </Group>
                    </Group>
                    <Textarea value={report} onChange={(event) => setReport(event.currentTarget.value)} autosize minRows={6} maxRows={12} />
                    {includeHer2 && (
                      <TextInput mt="sm" value={her2Text} onChange={(event) => setHer2Text(event.currentTarget.value)} />
                    )}
                    <Group mt="sm">
                      <Button leftSection={<IconPackageExport size={16} />} onClick={runExtract} loading={busy === "extract"}>
                        Generate Bundle
                      </Button>
                      <Button
                        variant="light"
                        leftSection={<IconDatabaseExport size={16} />}
                        disabled={!extractResult}
                        onClick={writeBundle}
                        loading={busy === "write"}
                      >
                        Write Bundle to FHIR Provider
                      </Button>
                      <Button
                        variant="light"
                        leftSection={<IconFileAnalytics size={16} />}
                        disabled={!extractResult}
                        onClick={runSummary}
                        loading={busy === "summary"}
                      >
                        Run FHIR2Summary
                      </Button>
                    </Group>
                  </Card>

                  {busy && (
                    <Group><Loader size="sm" /><Text size="sm">Working...</Text></Group>
                  )}

                  {extractResult && (
                    <Grid>
                      <Grid.Col span={{ base: 12, md: 6 }}>
                        <Card withBorder radius="sm" padding="md">
                          <Group justify="space-between" mb="xs">
                            <Text fw={600}>Selected resources</Text>
                            <Group gap={4}>
                              {Object.entries(resourceCounts).map(([type, count]) => (
                                <Badge key={type} variant="light">{type} {count}</Badge>
                              ))}
                            </Group>
                          </Group>
                          <Table verticalSpacing={4}>
                            <Table.Tbody>
                              {extractResult.resources.map((resource, index) => (
                                <Table.Tr key={index}>
                                  <Table.Td><Badge variant="light">{resource.resourceType}</Badge></Table.Td>
                                  <Table.Td>
                                    <Text size="sm">{resourceLabel(resource)}</Text>
                                    <Text size="xs" c="dimmed">{resourceValue(resource)}</Text>
                                  </Table.Td>
                                </Table.Tr>
                              ))}
                            </Table.Tbody>
                          </Table>
                        </Card>
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, md: 6 }}>
                        <Card withBorder radius="sm" padding="md">
                          <Text fw={600} mb="xs">Transaction Bundle</Text>
                          <JsonBlock value={extractResult.bundle} />
                        </Card>
                      </Grid.Col>
                    </Grid>
                  )}

                  {writeResult && (
                    <Card withBorder radius="sm" padding="md">
                      <Group justify="space-between" mb="xs">
                        <Text fw={600}>FHIR Proxy write</Text>
                        <Badge color="teal" variant="light">{writeResult.locations?.length || 0} resources</Badge>
                      </Group>
                      <Text size="sm">Provider: {writeResult.provider}</Text>
                      {writeResult.patient_id && <Text size="sm">Patient/{writeResult.patient_id}</Text>}
                      <JsonBlock value={writeResult.locations} />
                    </Card>
                  )}

                  {summary && (
                    <Card withBorder radius="sm" padding="md">
                      <Text fw={600} mb="xs">FHIR2Summary IPS output</Text>
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{summary}</Text>
                    </Card>
                  )}
                </Stack>
              </Grid.Col>
            </Grid>
          </Stack>
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
