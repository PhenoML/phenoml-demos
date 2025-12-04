# PhenoML Simple Server

A simple Node.js server for executing PhenoML workflows via HTTP requests.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Create a `.env` file with your PhenoML credentials:
```bash
cp .env.example .env
```

3. Edit `.env` and add your actual credentials:
```
PHENOML_USERNAME=your-username
PHENOML_PASSWORD=your-password
PHENOML_BASE_URL=your-base-url
PHENOML_WORKFLOW_ID=your-workflow-id
PORT=3000
```

## Running the Server

```bash
npm start
```

The server will start on `http://localhost:3000` (or the PORT you specified).

## Usage

Send a POST request to `/execute-workflow` with the following JSON payload:

```bash
curl -X POST http://localhost:3001/execute-workflow \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "your-workflow-id",
    "input_data": {
      "patient_last_name": "Kuphal",
      "patient_first_name": "Daren",
      "diagnosis_text": "generalized anxiety disorder"
    }
  }'
```

Note: If you set `PHENOML_WORKFLOW_ID` in your `.env` file, you can omit `workflow_id` from the request:

```bash
curl -X POST http://localhost:3001/execute-workflow \
  -H "Content-Type: application/json" \
  -d '{
    "input_data": {
      "patient_last_name": "Kuphal",
      "patient_first_name": "Daren",
      "diagnosis_text": "generalized anxiety disorder"
    }
  }'
```

### Health Check

```bash
curl http://localhost:3000/health
```

## Response Format

Success response (returns the workflow execution result directly):
```json
{
  "id": "execution-id",
  "status": "completed",
  ...
}
```

Error response:
```json
{
  "error": "Error message",
  "message": "Detailed error description"
}
```
