# Trial Protocol Coding

A demo application that extracts procedure names from clinical trial protocol JSON data and uses PhenoML to automatically code them with CPT (Current Procedural Terminology) codes.

## Overview

This script processes a JSON response from a clinical trial protocol analyzer, extracts procedure names from the Schedule of Assessments, and uses the PhenoML Construe API to map each procedure to appropriate CPT codes. Procedures that don't have CPT codes (typically administrative tasks) are logged as such.

## Prerequisites

- Python 3.11+
- PhenoML API credentials

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   Create a `.env` file in the project root with your PhenoML credentials:
   ```bash
   PHENOML_BASE_URL=your-phenoml-base-url
   PHENOML_USERNAME=your-username
   PHENOML_PASSWORD=your-password
   ```
   
   See `.env.example` for a template.

3. **Ensure data file exists:**
   The script expects a JSON file at `data/response_a2e1dd9a-51c6-4f85-835e-27577a784438.json`. This should be a response from a clinical trial protocol analyzer containing procedure data.

## Usage

Run the script:
```bash
python main.py
```

The script will:
- Extract procedure names from the JSON data
- Query PhenoML for CPT codes for each procedure
- Display results with codes, descriptions, and rationales
- Log procedures that don't have CPT codes (administrative tasks)

## Output

The script logs:
- **✓ Found codes**: Procedures with CPT codes, including code numbers, descriptions, and extraction rationales
- **○ No codes found**: Administrative procedures that don't map to CPT codes
- **✗ Error**: Any errors encountered during processing

## Example Output

```
Found 19 procedures with names

[1/19] Processing: Obtain informed consent
  ○ No CPT codes found (likely administrative procedure)

[3/19] Processing: Perform clinical assessment, including oral temperature and seated blood pressure
  ✓ Found 2 CPT code(s):
    - 99213: Office or other outpatient visit
      Rationale: Matches clinical assessment procedure
```
