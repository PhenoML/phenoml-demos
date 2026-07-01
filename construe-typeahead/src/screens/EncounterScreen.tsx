import { Badge, Stack } from '@mantine/core';
import { Panel } from '../components/Panel';
import { RowBuilder } from '../components/RowBuilder';
import { NoteField } from '../components/NoteField';
import type { CodeSystemSlug } from '../types';

// Problem list runs BOTH systems — SNOMED is the display/ranking system (its
// plain "Asthma" should beat the co-occurrent descriptors), and the top
// ICD-10-CM search result for the same query is attached for side-by-side
// code reveal. This is not cross-system mapping.
const PROBLEM_SYSTEMS: CodeSystemSlug[] = ['SNOMED_CT_US_LITE', 'ICD-10-CM'];
const MEDICATION_SYSTEMS: CodeSystemSlug[] = ['RXNORM'];

export function EncounterScreen() {
  return (
    <Stack gap="lg">
      <Panel
        title="Problem list"
        accent={<Badge variant="light" color="slate" radius="sm">SNOMED CT · ICD-10-CM</Badge>}
      >
        <RowBuilder
          kind="problem"
          systems={PROBLEM_SYSTEMS}
          cleanLabels
          label="Add a problem"
          hint="Type a condition — e.g. “asth”. We capture the selected SNOMED result plus the top ICD-10-CM result for the same query."
          placeholder="Start typing a condition…"
        />
      </Panel>

      <Panel
        title="Medications"
        accent={<Badge variant="light" color="slate" radius="sm">RxNorm</Badge>}
      >
        <RowBuilder
          kind="medication"
          systems={MEDICATION_SYSTEMS}
          label="Add a medication"
          hint="Type a drug name — e.g. “albut”."
          placeholder="Start typing a medication…"
        />
      </Panel>

      <Panel
        title="Clinical note"
        accent={<Badge variant="light" color="slate" radius="sm">SNOMED CT · semantic</Badge>}
      >
        <NoteField />
      </Panel>
    </Stack>
  );
}
