import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import './styles.css';
import { theme } from './theme';
import { AppStateProvider } from './hooks/useAppState';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <AppStateProvider>
        <App />
      </AppStateProvider>
    </MantineProvider>
  </React.StrictMode>,
);
