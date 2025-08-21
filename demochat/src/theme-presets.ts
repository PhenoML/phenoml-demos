import { MantineTheme} from '@mantine/core';

export interface FontOption {
  id: string;
  name: string;
  fontFamily: string;
  preview: string;
}

export interface CustomTheme {
  fontFamily: string;
  primaryColor: string;
  secondaryColor: string;
  tertiaryColor: string;
}

export interface ThemePreset {
  id: string;
  name: string;
  description: string;
  theme: Partial<MantineTheme>;
  preview: {
    primaryColor: string;
    secondaryColor: string;
    backgroundColor: string;
  };
}

export const fontOptions: FontOption[] = [
  {
    id: 'modern',
    name: 'Modern (Poppins)',
    fontFamily: 'Poppins, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    preview: 'Clean and friendly for customer support'
  },
  {
    id: 'professional',
    name: 'Professional (Inter)',
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    preview: 'Professional and readable for business'
  },
  {
    id: 'classic',
    name: 'Classic (Roboto)',
    fontFamily: 'Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    preview: 'Classic and versatile for all industries'
  },
  {
    id: 'elegant',
    name: 'Elegant (Source Sans Pro)',
    fontFamily: 'Source Sans Pro, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    preview: 'Elegant and sophisticated for premium brands'
  },
  {
    id: 'system',
    name: 'System (System UI)',
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    preview: 'Native system font for fast loading'
  }
];
