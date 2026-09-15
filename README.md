# phenoml demos

This repository contains demos built with phenoml!

### :robot: CMS inspired AI agents
**Location:** `demochat`

**Video:** [demo video link](https://www.youtube.com/watch?v=TqnFKw6PUHk)

**Key Features:**
- This demo demonstrates how to build healthcare AI agents with phenoml (see: `demochat/build_agents.ipynb`) and how they can be accessible via demo chat apps. 
- Running this demo requires a phenoml subscription. If you're interested in more granular agent customization check out a [reference example](https://github.com/PhenoML/phenoml_workshop_a2a_mcp) of how to build agents using our lang2FHIR API tools. 
- An example using a phenoml agent as a "bring your own LLM" with Vapi to add voice to your phenoml agent is demonstrated! See reference documentation from Vapi on connecting Vapi to a custom LLM [here](https://github.com/VapiAI/example-server-python-flask/blob/main/app/api/custom_llm.py). The voice agent is purely demonstrative and NOT intended for sensitive or production usage.

### :hospital: Trial Protocol Coding
**Location:** `trial-protocol-coding`

**Contributed by**: [@mattkoch614](https://github.com/mattkoch614)

**Key Features:**
- Extracts procedure names from clinical trial protocol JSON data (from Azure Content Understanding analyzer)
- Uses PhenoML Construe API to automatically code procedures with CPT codes
- Demonstrates processing structured healthcare data and mapping to standardized coding systems
- See the [README](trial-protocol-coding/README.md) for setup and usage instructions

### :syringe: GLP-1 Cohort Studio (lang2fhir + fhir2omop)
**Location:** `glp1-fhir2omop`

**Key Features:**
- Seeds synthetic GLP-1 data (Zepbound / Wegovy / Ozempic prescriptions, diagnoses, encounters, progress notes) onto a FHIR provider — with adverse-event language (headache, nausea) hidden in the *narrative* of 10% of the Ozempic patients' follow-up notes
- A small app runs **lang2fhir** over the notes to surface those findings as structured Conditions stored back on the same FHIR server
- Then runs **fhir2omop** over a selected cohort to produce OMOP CDM v5.4 tables (person, drug_exposure, condition_occurrence, ...) with concept mappings and CSV export
- Bonus: natural-language cohort selection via the **cohort** API
- See the [README](glp1-fhir2omop/README.md) for setup and usage

### about phenoml
:sparkles: [phenoml](https://phenoml.com/) is a developer platform for healthcare AI. 

- Read our [docs](https://developer.pheno.ml)
- Check out our [Youtube channel](https://www.youtube.com/@phenomldev)
- Come hang on [Discord](https://discord.gg/QgxDjNBxdV)
