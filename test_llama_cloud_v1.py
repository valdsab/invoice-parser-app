import os
import sys
import time
import json
import requests

def test_llama_cloud_v1_api():
    """
    Test the LlamaCloud API integration directly without using the application code.
    This matches the integration approach in utils.py and tests the API directly.
    """
    print("\n======== Testing LlamaCloud API Integration (V1) ========")
    
    try:
        # Start timer
        start_time = time.time()
        
        # Get API key from environment variable
        api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
        if not api_key:
            print("Error: LLAMA_CLOUD_API_ENTOS environment variable is not set")
            print("Please set the LLAMA_CLOUD_API_ENTOS environment variable to your LlamaCloud API key")
            return False
        
        # Mask the key in the log
        masked_key = api_key[:5] + "..." + api_key[-4:]
        print(f"API key found: {masked_key}")
        
        # Get test file
        test_dir = "uploads"
        if not os.path.exists(test_dir):
            os.makedirs(test_dir)
        
        test_file = os.path.join(test_dir, "sample_invoice.png")
        if not os.path.exists(test_file):
            print(f"Error: Test file not found at {test_file}")
            print("Please make sure there is a sample invoice file in the uploads directory")
            return False
        
        print(f"Using test file: {test_file}")
        print("Testing invoice parsing with LlamaCloud API (v1)...")
        print("This may take up to 60 seconds...")
        
        # Get file name
        file_name = os.path.basename(test_file)
        
        # Prepare API headers
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Step 1: Get presigned URL for upload
        print("Step 1: Requesting presigned URL for upload...")
        base_url = "https://api.cloud.llamaindex.ai"
        upload_url = f"{base_url}/api/v1/documents/upload-url"
        
        presigned_response = requests.post(
            upload_url,
            headers=headers,
            json={"fileName": file_name},
            timeout=30
        )
        
        if presigned_response.status_code != 200:
            print(f"Error getting presigned URL: {presigned_response.status_code}")
            print(f"Response: {presigned_response.text}")
            return False
            
        presigned_data = presigned_response.json()
        upload_data = presigned_data.get("data", {})
        document_id = upload_data.get("documentId")
        presigned_url = upload_data.get("uploadUrl")
        
        if not presigned_url or not document_id:
            print(f"Invalid presigned URL response: {presigned_data}")
            return False
            
        print(f"Received presigned URL. Document ID: {document_id}")
        
        # Step 2: Upload the file using the presigned URL
        print("Step 2: Uploading file...")
        with open(test_file, "rb") as file:
            file_content = file.read()
            
        upload_response = requests.put(
            presigned_url,
            data=file_content,
            headers={"Content-Type": "application/octet-stream"},
            timeout=30
        )
        
        if upload_response.status_code != 200:
            print(f"Error uploading file: {upload_response.status_code}")
            print(f"Response: {upload_response.text}")
            return False
            
        print("File uploaded successfully")
        
        # Step 3: Process the document for invoice extraction
        print("Step 3: Requesting invoice extraction...")
        process_url = f"{base_url}/api/v1/documents/{document_id}/process"
        process_data = {
            "processors": ["invoice-extraction"]
        }
        
        process_response = requests.post(
            process_url,
            headers=headers,
            json=process_data,
            timeout=30
        )
        
        if process_response.status_code != 200:
            print(f"Error requesting extraction: {process_response.status_code}")
            print(f"Response: {process_response.text}")
            return False
            
        process_result = process_response.json()
        
        # Get the task ID
        task_id = process_result.get("data", {}).get("taskId")
        if not task_id:
            print(f"Invalid process response, no task ID: {process_result}")
            return False
            
        print(f"Extraction task created: {task_id}")
        
        # Step 4: Poll for task completion
        print("Step 4: Waiting for extraction to complete...")
        task_url = f"{base_url}/api/v1/tasks/{task_id}"
        max_wait_time = 25
        poll_interval = 2.0
        polling_start = time.time()
        
        task_status = None
        while time.time() - polling_start < max_wait_time:
            task_response = requests.get(
                task_url,
                headers=headers,
                timeout=30
            )
            
            if task_response.status_code != 200:
                print(f"Error checking task status: {task_response.status_code}")
                print(f"Response: {task_response.text}")
                return False
                
            task_data = task_response.json().get("data", {})
            task_status = task_data.get("status")
            
            print(f"Current task status: {task_status}")
            
            if task_status == "COMPLETED":
                print("Invoice extraction completed successfully")
                break
            elif task_status in ("FAILED", "CANCELED"):
                error_details = task_data.get("errorDetails", "Unknown error")
                print(f"Invoice extraction failed with status: {task_status}. Error: {error_details}")
                return False
                
            # Wait before checking again
            time.sleep(poll_interval)
            
        # Check if we timed out
        if task_status != "COMPLETED":
            print(f"Extraction timed out or failed after {max_wait_time}s")
            return False
            
        # Step 5: Get extraction results
        print("Step 5: Retrieving extraction results...")
        results_url = f"{base_url}/api/v1/tasks/{task_id}/result"
        
        results_response = requests.get(
            results_url,
            headers=headers,
            timeout=30
        )
        
        if results_response.status_code != 200:
            print(f"Error retrieving results: {results_response.status_code}")
            print(f"Response: {results_response.text}")
            return False
            
        extraction_data = results_response.json().get("data", {})
        
        if not extraction_data:
            print("Empty extraction results received")
            return False
            
        # Calculate elapsed time
        elapsed = time.time() - start_time
        print(f"Processing completed in {elapsed:.1f} seconds")
        
        # Print extraction data structure
        print("\nExtraction data structure:")
        for key in extraction_data.keys():
            print(f"  {key}")
            
        # Save the extracted data to a file for further analysis
        output_path = os.path.join(test_dir, f"{os.path.splitext(file_name)[0]}_extracted.json")
        with open(output_path, 'w') as f:
            json.dump(extraction_data, f, indent=2)
            
        print(f"\nExtracted data saved to: {output_path}")
        
        # Try to display extracted information if available
        if "invoice" in extraction_data:
            invoice_data = extraction_data.get("invoice", {})
            print("\nExtracted Invoice Data:")
            print(f"  Vendor: {invoice_data.get('vendor', 'N/A')}")
            print(f"  Invoice Number: {invoice_data.get('invoiceNumber', 'N/A')}")
            print(f"  Date: {invoice_data.get('date', 'N/A')}")
            print(f"  Total: {invoice_data.get('total', 'N/A')}")
            
        if "lineItems" in extraction_data:
            line_items = extraction_data.get("lineItems", [])
            print(f"\nExtracted {len(line_items)} line items")
            
            if line_items:
                first_item = line_items[0]
                print("First line item:")
                for key, value in first_item.items():
                    print(f"  {key}: {value}")
                    
        return True
        
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        print("\nAPI integration test failed.")
        print("Possible issues:")
        print("1. The API key may be invalid or expired")
        print("2. Network connectivity issues")
        print("3. File format not supported")
        return False


if __name__ == "__main__":
    test_llama_cloud_v1_api()