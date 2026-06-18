import { Badge, Stack } from '@mantine/core';
import { Panel } from '../components/Panel';
import { RowBuilder } from '../components/RowBuilder';
import { NoteField } from '../components/NoteField';
import type { CodeSystemSlug } from '../types';

// Problem list runs BOTH systems — SNOMED is the display/ranking system (its
// plain "Asthma" should beat the co-occurrent descriptors), and the top
// ICD-10-CM hit is attached so each problem stores both codes.
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
          label="Add a problem"
          hint="Type a condition — e.g. “asth”. Each problem is stored as both a SNOMED and an ICD-10-CM code."
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
