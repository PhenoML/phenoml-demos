import { createTheme, type MantineColorsTuple } from '@mantine/core';

// Bespoke palette so the app doesn't read as default Mantine.
// Primary: a deep clinical teal. Accent: a warm coral for the "coded" moments.
const teal: MantineColorsTuple = [
  '#e4faf4',
  '#c3f0e6',
  '#97e5d4',
  '#67d9c0',
  '#42cfb1',
  '#2ec7a7',
  '#1fb89a',
  '#0f9e84',
  '#00806b',
  '#005f50',
];

const coral: MantineColorsTuple = [
  '#fff0ec',
  '#ffded4',
  '#ffbaa8',
  '#ff9377',
  '#fd724e',
  '#fc5d34',
  '#fc5126',
  '#e14219',
  '#c93812',
  '#b02c07',
];

// Cool slate for surfaces and text.
const slate: MantineColorsTuple = [
  '#f5f7f9',
  '#e9edf1',
  '#cfd8e0',
  '#b2c0cd',
  '#98abbc',
  '#869cb0',
  '#7c93aa',
  '#697f95',
  '#5b7185',
  '#4a6175',
];

export const theme = createTheme({
  primaryColor: 'teal',
  primaryShade: 7,
  colors: { teal, coral, slate },
  fontFamily:
    "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMonospace:
    "'JetBrains Mono', 'SF Mono', 'Fira Code', ui-monospace, monospace",
  headings: {
    fontFamily: "Fraunces, Georgia, 'Times New Roman', serif",
    fontWeight: '600',
  },
  defaultRadius: 'lg',
  radius: {
    xs: '6px',
    sm: '9px',
    md: '12px',
    lg: '16px',
    xl: '22px',
  },
  shadows: {
    xs: '0 1px 2px rgba(16, 42, 67, 0.06)',
    sm: '0 2px 8px rgba(16, 42, 67, 0.08)',
    md: '0 8px 24px rgba(16, 42, 67, 0.10)',
    lg: '0 18px 48px rgba(16, 42, 67, 0.14)',
    xl: '0 28px 72px rgba(16, 42, 67, 0.18)',
  },
  cursorType: 'pointer',
});

// Shared design tokens used outside Mantine props (inline styles / gradients).
export const tokens = {
  ink: '#102a43',
  inkSoft: '#486581',
  surface: '#ffffff',
  canvas: '#eef2f6',
  canvasTop: '#f6f9fb',
  border: '#dbe3ec',
  codeBg: '#0f2233',
  codeInk: '#7fe8d2',
};
