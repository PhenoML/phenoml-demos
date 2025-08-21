# DemoChat

A simple React chat widget for web apps and Chrome extensions demonstrating usage of agents built with PhenoML.

## Quick Start

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Run demo:**
   ```bash
   npm run dev
   # Visit http://localhost:5173/example.html
   ```

## Usage

### React App
```jsx
import { ChatWidget } from '@phenoml/chat-widget';

<ChatWidget 
  title="Chat"
  apiEndpoint="https://api.yoursite.com/chat"
/>
```

### Chrome Extension
```bash
npm run build-extension
# Load dist-extension/ folder in Chrome Extensions
```

## Backend (Optional)

Python FastAPI example included:

```bash
pip install -r requirements.txt
python app.py
```

## Build

```bash
npm run build              # NPM package
npm run build-extension    # Chrome extension
```