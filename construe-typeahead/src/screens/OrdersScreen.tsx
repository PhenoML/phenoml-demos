import { Badge, Stack } from '@mantine/core';
import { Panel } from '../components/Panel';
import { RowBuilder } from '../components/RowBuilder';
import type { CodeSystemSlug } from '../types';

const ORDER_SYSTEMS: CodeSystemSlug[] = ['LOINC'];

export function OrdersScreen() {
  return (
    <Stack gap="lg">
      <Panel
        title="Order entry"
        accent={<Badge variant="light" color="slate" radius="sm">LOINC</Badge>}
      >
        <RowBuilder
          kind="order"
          systems={ORDER_SYSTEMS}
          label="Add an order"
          hint="Type a lab or panel — e.g. “lipid panel”. The same accept-commits-code pattern, coded to LOINC."
          placeholder="Start typing an order…"
        />
      </Panel>
    </Stack>
  );
}
