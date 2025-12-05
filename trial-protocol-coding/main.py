#!/usr/bin/env python3
"""
Main entry point for trial protocol coding demo.
Extracts procedure names from JSON and uses PhenoML to code them with CPT codes.
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv
from phenoml import Client


def load_json_file(filepath: str) -> dict:
    """Load and parse JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def extract_procedure_names(data: dict) -> list[str]:
    """
    Extract procedure names from nested procedures_list structures in the JSON.
    
    Navigates through: contents -> fields -> procedures_list -> valueArray 
                       -> valueObject -> procedure_name -> valueString
    """
    procedure_names = []
    
    # Navigate through the result contents
    if 'result' in data and 'contents' in data['result']:
        for content in data['result']['contents']:
            if 'fields' in content:
                fields = content['fields']
                
                # Look for procedures_list in the fields
                if 'procedures_list' in fields:
                    procedures_list = fields['procedures_list']
                    
                    # Extract from valueArray
                    if 'valueArray' in procedures_list:
                        for item in procedures_list['valueArray']:
                            if 'valueObject' in item:
                                value_obj = item['valueObject']
                                
                                # Get procedure_name if it has valueString
                                if 'procedure_name' in value_obj:
                                    proc_name = value_obj['procedure_name']
                                    if 'valueString' in proc_name:
                                        procedure_names.append(proc_name['valueString'])
    
    return procedure_names


def code_procedure(client: Client, procedure_text: str) -> dict:
    """
    Use PhenoML construe to extract CPT codes for a procedure.
    
    Args:
        client: PhenoML Client instance
        procedure_text: The procedure name/description to code
        
    Returns:
        Response from the construe API
    """
    response = client.construe.extract_codes(
        text=procedure_text,
        system={
            "version": "2025",
            "name": "CPT"
        },
        config={
            "chunking_method": "none",
            "max_codes_per_chunk": 20,
            "code_similarity_filter": 0.9,
            "include_rationale": True
        }
    )
    
    return response


def main():
    """Main execution function."""
    # Load environment variables
    load_dotenv()
    
    base_url = os.getenv('PHENOML_BASE_URL')
    username = os.getenv('PHENOML_USERNAME')
    password = os.getenv('PHENOML_PASSWORD')
    
    if not all([base_url, username, password]):
        raise ValueError("Missing required environment variables: PHENOML_BASE_URL, PHENOML_USERNAME, PHENOML_PASSWORD")
    
    # Initialize PhenoML client
    client = Client(
        username=username,
        password=password,
        base_url=base_url
    )
    
    # Load JSON data
    data_dir = Path(__file__).parent / 'data'
    json_file = data_dir / 'response_a2e1dd9a-51c6-4f85-835e-27577a784438.json'
    
    if not json_file.exists():
        raise FileNotFoundError(f"JSON file not found: {json_file}")
    
    data = load_json_file(json_file)
    
    # Extract procedure names
    procedures = extract_procedure_names(data)
    print(f"Found {len(procedures)} procedures with names")
    
    # Process each procedure
    for i, procedure_name in enumerate(procedures, 1):
        print(f"\n[{i}/{len(procedures)}] Processing: {procedure_name}")
        
        try:
            result = code_procedure(client, procedure_name)
            print(f"  ✓ Coded successfully")
            # TODO: Store or display results as needed
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    print("\nDone!")


if __name__ == "__main__":
    main()

