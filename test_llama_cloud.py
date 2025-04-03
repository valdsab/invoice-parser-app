import os
import time
import requests
import json
import base64
import glob
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_llama_cloud_api():
    """
    Test the LlamaCloud API integration directly without using the application code.
    This avoids circular import issues and tests the API directly.
    """
    
    print("\n======== Testing LlamaCloud API Integration ========")
    
    # Check if API key is set
    api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
    if not api_key:
        print("ERROR: LLAMA_CLOUD_API_ENTOS is not set in environment variables.")
        print("Please set the API key and try again.")
        return False
    
    print(f"API key found: {api_key[:4]}...{api_key[-4:]}")
    
    # Check if test file exists
    test_dir = "uploads"
    os.makedirs(test_dir, exist_ok=True)
    
    # Check if there are any existing files to test with
    test_files = glob.glob(os.path.join(test_dir, "*.pdf")) + \
                 glob.glob(os.path.join(test_dir, "*.png")) + \
                 glob.glob(os.path.join(test_dir, "*.jpg")) + \
                 glob.glob(os.path.join(test_dir, "*.jpeg"))
    
    if not test_files:
        print("No test files found in 'uploads' directory.")
        print("Please add a test invoice (PDF or image) to the 'uploads' directory.")
        return False
    
    test_file_path = test_files[0]
    print(f"Using test file: {test_file_path}")
    
    # Process the file with LlamaCloud API directly
    try:
        print("Sending file to LlamaCloud API for processing...")
        print("This may take up to 60 seconds...")
        
        # Read file as binary data
        with open(test_file_path, 'rb') as f:
            file_data = f.read()
        
        # Prepare API request
        file_name = Path(test_file_path).name
        mime_type = "application/pdf" if file_name.endswith(".pdf") else "image/png"
        
        # LlamaCloud API endpoints
        upload_url = "https://api.cloud.llamaindex.ai/api/parsing/upload"
        
        # Track time for informational purposes
        start_time = time.time()
        
        # Step 1: Upload file to LlamaCloud
        print("Step 1: Uploading file...")
        
        # Try with Bearer token authentication instead of x-api-key
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Use multipart/form-data upload instead of JSON
        files = {
            'file': (file_name, file_data, mime_type)
        }
        
        # Headers for multipart upload - no content-type here, requests will set it
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        
        # Send upload request with files parameter for multipart/form-data
        upload_response = requests.post(
            upload_url,
            headers=headers,
            files=files
        )
        
        # Handle upload response
        if upload_response.status_code != 200:
            print(f"Error uploading file: {upload_response.status_code}")
            print(f"Response: {upload_response.text}")
            return False
        
        upload_data = upload_response.json()
        # In the new API version, the job ID is the 'id' field
        job_id = upload_data.get("id")
        
        if not job_id:
            print("No job ID returned from upload request")
            print(f"Response: {upload_data}")
            return False
        
        job_status = upload_data.get("status")
        print(f"Upload successful. Job ID: {job_id}, Status: {job_status}")
        
        # Step 2: Poll for job completion
        print("Step 2: Waiting for processing to complete...")
        
        status_url = f"https://api.cloud.llamaindex.ai/api/parsing/job/{job_id}"
        
        max_retries = 15
        retry_count = 0
        polling_interval = 5  # Increase polling interval to reduce API calls
        
        while retry_count < max_retries:
            # Get job status
            status_response = requests.get(status_url, headers=headers)
            
            if status_response.status_code != 200:
                print(f"Error checking job status: {status_response.status_code}")
                print(f"Response: {status_response.text}")
                return False
            
            status_data = status_response.json()
            
            # Debug: Print full status response
            print(f"Status response: {status_data}")
            
            # Check if processing is complete (API uses uppercase statuses: SUCCESS, ERROR, etc.)
            if "status" in status_data and status_data["status"] in ["COMPLETE", "complete", "SUCCESS", "success"]:
                print("Processing complete!")
                break
            
            # Check for error
            if "status" in status_data and status_data["status"] in ["ERROR", "error"]:
                print(f"Processing error: {status_data.get('error_message', status_data.get('error', 'Unknown error'))}")
                return False
            
            # Wait before retrying
            print(f"Job still processing... (Attempt {retry_count + 1}/{max_retries})")
            time.sleep(polling_interval)
            retry_count += 1
        
        if retry_count >= max_retries:
            print("Timed out waiting for job to complete")
            return False
        
        # Step 3: Get results 
        print("Step 3: Retrieving results...")
        
        # Since we couldn't find an obvious result endpoint, let's try to get the info from the status endpoint
        # and look for a results_url or data field
        result_url = f"https://api.cloud.llamaindex.ai/api/parsing/job/{job_id}"
        
        # Also, let's try to add a detailed flag to get more information
        result_params = {"detailed": "true"}
        result_response = requests.get(result_url, headers=headers, params=result_params)
        
        if result_response.status_code != 200:
            print(f"Error retrieving results: {result_response.status_code}")
            print(f"Response: {result_response.text}")
            return False
        
        # Parse result data
        result_data = result_response.json()
        
        # Calculate elapsed time
        elapsed = time.time() - start_time
        print(f"Processing completed in {elapsed:.1f} seconds")
        
        # Debug: Print full result structure
        print("Result data structure:")
        for key in result_data.keys():
            print(f"  {key}")
        
        # The response format may vary, try different possible structures
        # First check for the direct invoice field
        if "invoice" in result_data:
            invoice_data = result_data.get("invoice", {})
            print("\nExtracted Invoice Data:")
            print(f"  Vendor: {invoice_data.get('vendor', 'N/A')}")
            print(f"  Invoice Number: {invoice_data.get('invoice_number', 'N/A')}")
            print(f"  Invoice Date: {invoice_data.get('invoice_date', 'N/A')}")
            print(f"  Total Amount: {invoice_data.get('total_amount', 'N/A')}")
        # Check for data > document structure 
        elif "data" in result_data and "document" in result_data.get("data", {}):
            doc_data = result_data.get("data", {}).get("document", {})
            print("\nExtracted Invoice Data (from document):")
            print(f"  Vendor: {doc_data.get('vendor', 'N/A')}")
            print(f"  Invoice Number: {doc_data.get('invoice_number', 'N/A')}")
            print(f"  Invoice Date: {doc_data.get('date', doc_data.get('invoice_date', 'N/A'))}")
            print(f"  Total Amount: {doc_data.get('total', doc_data.get('total_amount', 'N/A'))}")
        
        # Try to find line items in multiple possible locations
        line_items = []
        
        # Check standard location
        if "data" in result_data and "line_items" in result_data.get("data", {}):
            line_items = result_data.get("data", {}).get("line_items", [])
        # Check direct line_items field
        elif "line_items" in result_data:
            line_items = result_data.get("line_items", [])
        # Check document > line_items
        elif "data" in result_data and "document" in result_data.get("data", {}) and "line_items" in result_data.get("data", {}).get("document", {}):
            line_items = result_data.get("data", {}).get("document", {}).get("line_items", [])
            
        if line_items:
            print(f"\nExtracted {len(line_items)} line items")
            
            if len(line_items) > 0:
                first_item = line_items[0]
                print("First line item fields:")
                for key, value in first_item.items():
                    print(f"  {key}: {value}")
        
        # Check for errors
        if "error" in result_data:
            print(f"Error in result data: {result_data.get('error')}")
        
        # Save the extracted data to a file for further analysis
        output_path = os.path.join(test_dir, f"{os.path.splitext(file_name)[0]}_extracted.json")
        with open(output_path, 'w') as f:
            json.dump(result_data, f, indent=2)
        
        print(f"\nExtracted data saved to: {output_path}")
        
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
    test_llama_cloud_api()