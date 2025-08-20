import { createRoot } from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { ChatWidget } from './ChatWidget';
import { IconStethoscope } from '@tabler/icons-react';
import '@mantine/core/styles.css';

function App() {
  return (
    <MantineProvider theme={{ fontFamily: 'Inter, sans-serif' }}>
      <div style={{ 
        padding: '40px', 
        display: 'flex', 
        justifyContent: 'center', 
        minHeight: '100vh',
        backgroundColor: '#f8f9fa'
      }}>
        <div style={{ width: '100%', maxWidth: '400px' }}>
          <ChatWidget
          // Replace with your own API endpoint
            apiEndpoint="http://127.0.0.1:8001/chat"
            title="Pheno Health Chat"
            subtitle="Connected to your agent"
            placeholder="Ask me anything..."
            height={600}
            primaryColor="#0076A6"
            // headerIcon={<IconStethoscope size={22} />}
            showHeaderIcon={true}
          />
        </div>
      </div>
    </MantineProvider>
  );
}

const container = document.getElementById('root');
if (container) {
  const root = createRoot(container);
  root.render(<App />);
}