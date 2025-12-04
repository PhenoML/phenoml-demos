// Simple Node.js server for executing PhenoML workflows
import express from 'express';
import { PhenoMLClient } from 'phenoml';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 3000;
const WORKFLOW_ID = process.env.WORKFLOW_ID;

app.use(express.json());

app.post('/execute-workflow', async (req, res) => {
  try {
    const { input_data } = req.body;

    // Validate input_data is provided
    if (!input_data || typeof input_data !== 'object') {
      return res.status(400).json({ error: 'input_data object is required' });
    }

    const workflowId = WORKFLOW_ID;

    // Get credentials from environment variables
    const username = process.env.PHENOML_USERNAME;
    const password = process.env.PHENOML_PASSWORD;
    const baseUrl = process.env.PHENOML_BASE_URL || "https://experiment.app.pheno.ml";

    if (!username || !password) {
      return res.status(500).json({ error: 'PhenoML credentials are not configured' });
    }

    // Initialize PhenoML client
    const client = new PhenoMLClient({
      username,
      password,
      baseUrl
    });

    // Execute the workflow
    const result = await client.workflows.execute(workflowId, {
      input_data
    });

    res.json(result);
  } catch (error) {
    console.error('Workflow execution failed:', error);
    res.status(500).json({
      error: 'Workflow execution failed',
      message: error instanceof Error ? error.message : String(error)
    });
  }
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.listen(PORT, () => {
  console.log(`PhenoML workflow server running on http://localhost:${PORT}`);
  console.log(`POST to http://localhost:${PORT}/execute-workflow to execute workflows`);
});
