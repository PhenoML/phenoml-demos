import React from 'react';
import { createRoot } from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { ChatWidget } from './ChatWidget';
import '@mantine/core/styles.css';

function ExtensionApp() {
  return (
    <MantineProvider>
      <div style={{ width: '350px', height: '500px' }}>
        <ChatWidget
          
          apiEndpoint="http://127.0.0.1:8001/chat"
          title="PhenoML Extension"
          subtitle="Connected to your PhenoML agent"
          placeholder="Ask anything..."
          height={500}
        />
      </div>
    </MantineProvider>
  );
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('root');
  if (container) {
    const root = createRoot(container);
    root.render(<ExtensionApp />);
  }
});