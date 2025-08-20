import React, { useState, useRef, useEffect } from 'react';
import { 
  Box, 
  Paper, 
  Text, 
  TextInput, 
  ActionIcon, 
  Stack, 
  Group,
  ScrollArea,
  Loader,
  Title
} from '@mantine/core';
import { IconSend, IconClipboard } from '@tabler/icons-react';

interface Message {
  id: string;
  text: string;
  sender: 'user' | 'bot';
  timestamp: Date;
}

export interface ChatWidgetProps {
  apiEndpoint?: string;
  title?: string;
  subtitle?: string;
  placeholder?: string;
  height?: number;
  onMessage?: (message: string) => Promise<string>;
  // Theme customization props
  primaryColor?: string;
  secondaryColor?: string;
  tertiaryColor?: string;
  fontFamily?: string;
  // Icon customization props
  headerIcon?: React.ReactNode;
  showHeaderIcon?: boolean;
}

export function ChatWidget({
  apiEndpoint = '/chat',
  title = 'Chat Assistant',
  subtitle = 'How can we help you?',
  placeholder = 'Type your message...',
  height = 500,
  onMessage,
  primaryColor = 'blue',
  secondaryColor,
  tertiaryColor,
  headerIcon = <IconClipboard size={20} />,
  showHeaderIcon = true
}: ChatWidgetProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      text: 'Hello! How can I assist you today?',
      sender: 'bot',
      timestamp: new Date()
    }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTo({ top: scrollAreaRef.current.scrollHeight });
    }
  }, [messages]);

  const sendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      text: inputValue,
      sender: 'user',
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);

    try {
      let response: string;
      
      if (onMessage) {
        response = await onMessage(inputValue);
      } else {
        const res = await fetch(apiEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: inputValue,
            session_id: sessionId
          })
        });

        if (!res.ok) throw new Error('Failed to send message');
        
        const data = await res.json();
        response = data.response;
        if (data.session_id) setSessionId(data.session_id);
      }

      const botMessage: Message = {
        id: (Date.now() + 1).toString(),
        text: response,
        sender: 'bot',
        timestamp: new Date()
      };

      setMessages(prev => [...prev, botMessage]);
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        text: 'Sorry, there was an error processing your message.',
        sender: 'bot',
        timestamp: new Date()
      };
      setMessages(prev => [...prev, errorMessage]);
    }

    setIsLoading(false);
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter') {
      sendMessage();
    }
  };

  return (
    <Paper 
      shadow="sm" 
      radius="md" 
      p={0} 
      style={{ 
        height, 
        overflow: 'hidden',
        fontFamily: 'inherit' // Inherit font from parent
      }}
    >
      {/* Header */}
      <Box 
        p="md" 
        c="white"
        style={{ 
          backgroundColor: primaryColor.startsWith('#') ? primaryColor : `var(--mantine-color-${primaryColor}-6)` 
        }}
      >
        <Group justify="space-between" align="center">
          <div>
            <Title order={4} style={{ fontFamily: 'inherit' }}>{title}</Title>
            <Text size="sm" opacity={0.9} style={{ fontFamily: 'inherit' }}>{subtitle}</Text>
          </div>
          {showHeaderIcon && (
            <Box c="white" style={{ opacity: 0.9 }}>
              {headerIcon}
            </Box>
          )}
        </Group>
      </Box>

      {/* Messages */}
      <ScrollArea 
        h={height - 140} 
        p="md" 
        viewportRef={scrollAreaRef}
        style={{ backgroundColor: tertiaryColor || '#f8f9fa' }}
      >
        <Stack gap="sm">
          {messages.map((message) => (
            <Group key={message.id} justify={message.sender === 'user' ? 'flex-end' : 'flex-start'}>
              <Paper
                p="md"
                radius="md"
                shadow="xs"
                c={message.sender === 'user' ? 'white' : 'dark'}
                style={{ 
                  maxWidth: '80%',
                  backgroundColor: message.sender === 'user' 
                    ? (primaryColor.startsWith('#') ? primaryColor : `var(--mantine-color-${primaryColor}-6)`)
                    : (secondaryColor || 'white')
                }}
              >
                <Text size="sm" style={{ fontFamily: 'inherit' }}>{message.text}</Text>
              </Paper>
            </Group>
          ))}
          {isLoading && (
            <Group justify="flex-start">
              <Paper p="sm" radius="lg" bg="gray.1">
                <Loader size="sm" />
              </Paper>
            </Group>
          )}
        </Stack>
      </ScrollArea>

      {/* Input */}
      <Box p="md" style={{ borderTop: '1px solid #e9ecef' }}>
        <Group gap="xs">
          <TextInput
            flex={1}
            placeholder={placeholder}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyPress}
            disabled={isLoading}
            style={{ fontFamily: 'inherit' }}
          />
          <ActionIcon 
            variant="filled" 
            size="lg"
            onClick={sendMessage}
            disabled={!inputValue.trim() || isLoading}
            style={{
              backgroundColor: primaryColor.startsWith('#') ? primaryColor : `var(--mantine-color-${primaryColor}-6)`
            }}
          >
            <IconSend size={16} />
          </ActionIcon>
        </Group>
      </Box>
    </Paper>
  );
}