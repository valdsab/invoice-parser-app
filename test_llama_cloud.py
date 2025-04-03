import os
import json
import logging
import requests
import tempfile
import re

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_llama_cloud_api():
    """
    Test the LlamaCloud API integration directly without using the application code.
    This avoids circular import issues and tests the API directly.
    """
    
    print("\n======== Testing LlamaCloud API Directly ========")
    
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
    test_files = [f for f in os.listdir(test_dir) if f.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg'))]
    
    if not test_files:
        print("No test files found in 'uploads' directory.")
        print("Please add a test invoice (PDF or image) to the 'uploads' directory.")
        return False
    
    test_file_path = os.path.join(test_dir, test_files[0])
    print(f"Using test file: {test_file_path}")
    
    # Process the file with LlamaCloud directly
    try:
        print("Sending file directly to LlamaCloud for processing...")
        
        # Step 1: Get presigned URL for upload
        # Try different header formats for API authentication
        print(f"Using API key: {api_key[:4]}...{api_key[-4:]}")
        
        # Try different header formats
        print("Trying different header formats...")
        
        # Format 1: API key directly in x-api-key header
        headers1 = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        print("1. Using x-api-key header format")
        
        # Format 2: Bearer token in Authorization header
        headers2 = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        print("2. Using Authorization: Bearer token format")
        
        # Start with format 1
        headers = headers1
        
        # First get a presigned URL for upload
        presigned_url_request = {
            "fileName": os.path.basename(test_file_path),
            "contentType": "application/pdf"  # Adjust based on file type
        }
        
        print("Requesting presigned URL...")
        # Try alternative API endpoint format
        print("Trying different LlamaCloud API endpoint formats...")
        
        # Try different endpoint formats
        # Option 1 - Standard path
        api_url = "https://api.cloud.llamaindex.ai/api/v1/documents/upload-url"
        print(f"Trying API URL 1: {api_url}")
        
        # Option 2 - Alternative path without 'api' prefix
        api_url2 = "https://cloud.llamaindex.ai/api/v1/documents/upload-url"
        print(f"Trying API URL 2: {api_url2}")
        
        # Try first URL
        print(f"Attempting with API URL 1: {api_url}")
        presigned_response = requests.post(
            api_url,
            headers=headers,
            json=presigned_url_request
        )
        
        # If first URL fails, try the second URL with the same headers
        if not presigned_response.ok:
            print(f"First URL failed with: {presigned_response.status_code} - {presigned_response.text}")
            print(f"Attempting with API URL 2: {api_url2}")
            presigned_response = requests.post(
                api_url2,
                headers=headers,
                json=presigned_url_request
            )
            
        # If both URLs fail with headers1, try headers2
        if not presigned_response.ok:
            print(f"Both URLs failed with header format 1")
            print("Switching to header format 2 (Bearer token)")
            
            headers = headers2
            
            # Try URL 1 with new headers
            print(f"Trying URL 1 with header format 2")
            presigned_response = requests.post(
                api_url,
                headers=headers,
                json=presigned_url_request
            )
            
            # If URL 1 fails with headers2, try URL 2
            if not presigned_response.ok:
                print(f"URL 1 failed with header format 2")
                print(f"Trying URL 2 with header format 2")
                presigned_response = requests.post(
                    api_url2,
                    headers=headers,
                    json=presigned_url_request
                )
        
        
        if not presigned_response.ok:
            print(f"Error getting presigned URL: {presigned_response.status_code} - {presigned_response.text}")
            
            # The API may have been updated or the key may have expired
            print("\nAll API endpoint and auth combinations failed.")
            print("Possible issues:")
            print("1. The API key may be invalid or expired")
            print("2. The API endpoint pattern may have changed")
            print("3. The API may require additional authentication")
            print("4. Network connectivity issues")
            
            return False
        
        # Get the upload URL and document ID - NOTE: There may be a nested 'data' field
        presigned_data = presigned_response.json()
        print(f"Response structure: {json.dumps(presigned_data, indent=2)}")
        
        # Try both formats - direct fields or nested under 'data'
        if "data" in presigned_data:
            print("Found nested 'data' field in response")
            upload_data = presigned_data.get("data", {})
            upload_url = upload_data.get("uploadUrl")
            document_id = upload_data.get("documentId")
        else:
            print("Using direct fields in response")
            upload_url = presigned_data.get("uploadUrl")
            document_id = presigned_data.get("documentId")
        
        if not upload_url or not document_id:
            print("Invalid presigned URL response - missing uploadUrl or documentId")
            return False
        
        print(f"Got presigned URL and document ID: {document_id}")
        
        # Step 2: Upload file to presigned URL
        print("Uploading file to presigned URL...")
        with open(test_file_path, "rb") as file:
            upload_response = requests.put(
                upload_url,
                data=file,
                headers={"Content-Type": "application/pdf"}  # Adjust based on file type
            )
            
            if not upload_response.ok:
                print(f"Error uploading file: {upload_response.status_code} - {upload_response.text}")
                return False
        
        print("File uploaded successfully")
        
        # Step 3: Process the document for invoice extraction - using the pattern from utils.py
        # First, let's try the document/process endpoint pattern from utils.py
        process_url = f"{api_url.split('/api/v1/')[0]}/api/v1/documents/{document_id}/process"
        print(f"Using process URL: {process_url}")
        
        process_data = {
            "processors": ["invoice-extraction"]  # Note: utils.py uses "processors" not "extractors"
        }
        
        print("Requesting invoice extraction...")
        process_response = requests.post(
            process_url,
            headers=headers,
            json=process_data
        )
        
        # Handle possible response issues
        if not process_response.ok:
            print(f"Error requesting extraction: {process_response.status_code} - {process_response.text}")
            
            # Try the alternative extraction endpoint that we were using before
            alternative_url = f"{api_url.split('/api/v1/')[0]}/api/v1/extractions"
            print(f"Trying alternative extraction URL: {alternative_url}")
            
            alternative_data = {
                "documentId": document_id,
                "extractors": ["invoice"]  # Original parameter name
            }
            
            process_response = requests.post(
                alternative_url,
                headers=headers,
                json=alternative_data
            )
            
            if not process_response.ok:
                print(f"Both extraction endpoints failed: {process_response.status_code} - {process_response.text}")
                return False
        
        # Process the response
        process_result = process_response.json()
        print(f"Process response: {json.dumps(process_result, indent=2)}")
        
        # Try to get the task ID, which might be in different places depending on the endpoint
        task_id = None
        
        # Option 1: In the data field (utils.py pattern)
        if "data" in process_result and "taskId" in process_result.get("data", {}):
            task_id = process_result.get("data", {}).get("taskId")
            print(f"Found taskId in data field: {task_id}")
        # Option 2: As extractionId (our previous pattern)
        elif "extractionId" in process_result:
            task_id = process_result.get("extractionId")
            print(f"Found extractionId field: {task_id}")
        
        if not task_id:
            print(f"Invalid process response, no task ID or extraction ID found: {process_result}")
            return False
        
        print(f"Got task/extraction ID: {task_id}")
        
        # Step 4: Poll for task completion - try both patterns
        # Option 1: tasks endpoint (utils.py)
        task_url = f"{api_url.split('/api/v1/')[0]}/api/v1/tasks/{task_id}"
        # Option 2: extractions endpoint (our original)
        extraction_url = f"{api_url.split('/api/v1/')[0]}/api/v1/extractions/{task_id}"
        
        print(f"Will try both task URLs:")
        print(f"  1. Task URL: {task_url}")
        print(f"  2. Extraction URL: {extraction_url}")
        
        max_attempts = 20
        attempt = 0
        status = "pending"
        status_data = None
        
        print("Checking extraction status...")
        while status in ("pending", "PENDING") and attempt < max_attempts:
            attempt += 1
            
            # Try the first URL format
            print(f"Attempt {attempt}/{max_attempts} - Trying task URL...")
            try:
                status_response = requests.get(
                    task_url,
                    headers=headers
                )
                
                if status_response.ok:
                    status_data = status_response.json()
                    if "data" in status_data:
                        status = status_data.get("data", {}).get("status", "").upper()
                    else:
                        status = status_data.get("status", "").upper()
                    print(f"Task status: {status}")
                else:
                    print(f"Task URL failed: {status_response.status_code}")
                    
                    # Try the second URL format
                    print("Trying extraction URL...")
                    status_response = requests.get(
                        extraction_url,
                        headers=headers
                    )
                    
                    if status_response.ok:
                        status_data = status_response.json()
                        status = status_data.get("status", "").upper()
                        print(f"Extraction status: {status}")
                    else:
                        print(f"Extraction URL also failed: {status_response.status_code}")
                        status = "FAILED"
            except Exception as e:
                print(f"Error checking status: {str(e)}")
                status = "FAILED"
            
            if status in ("COMPLETED", "completed"):
                print("Extraction completed successfully!")
                
                # Get the results
                # Option 1: In the status_data directly
                invoice_data = None
                if "invoice" in status_data:
                    invoice_data = status_data.get("invoice", {})
                # Option 2: Need to fetch results from a separate endpoint
                elif task_id:
                    results_url = f"{api_url.split('/api/v1/')[0]}/api/v1/tasks/{task_id}/result"
                    print(f"Fetching results from: {results_url}")
                    
                    try:
                        results_response = requests.get(
                            results_url,
                            headers=headers
                        )
                        if results_response.ok:
                            results_data = results_response.json()
                            if "data" in results_data:
                                invoice_data = results_data.get("data", {})
                            else:
                                invoice_data = results_data
                        else:
                            print(f"Error fetching results: {results_response.status_code}")
                    except Exception as e:
                        print(f"Error fetching results: {str(e)}")
                
                if invoice_data:
                    print("\nExtracted Invoice Data:")
                    print(f"Data structure: {json.dumps(invoice_data, indent=2)[:500]}...")
                    
                    # Try to extract key fields - handle different formats
                    # Format 1: Direct fields
                    vendor_name = "Unknown"
                    invoice_number = "Unknown"
                    invoice_date = "Unknown"
                    total_amount = 0
                    
                    if "vendor" in invoice_data:
                        vendor = invoice_data.get("vendor", {})
                        if isinstance(vendor, dict):
                            vendor_name = vendor.get("name", "Unknown")
                    elif "vendorName" in invoice_data:
                        vendor_name = invoice_data.get("vendorName", "Unknown")
                    
                    if "invoiceNumber" in invoice_data:
                        invoice_number = invoice_data.get("invoiceNumber", "Unknown")
                    
                    if "invoiceDate" in invoice_data:
                        invoice_date = invoice_data.get("invoiceDate", "Unknown")
                    
                    if "totalAmount" in invoice_data:
                        total_amount_data = invoice_data.get("totalAmount", {})
                        if isinstance(total_amount_data, dict):
                            total_amount = total_amount_data.get("amount", 0)
                        else:
                            total_amount = total_amount_data
                    
                    print(f"Vendor: {vendor_name}")
                    print(f"Invoice #: {invoice_number}")
                    print(f"Date: {invoice_date}")
                    print(f"Total: ${total_amount}")
                    
                    # Display line items if available
                    line_items = invoice_data.get("lineItems", [])
                    if line_items:
                        print(f"\nLine Items ({len(line_items)}):")
                        for i, item in enumerate(line_items):
                            if isinstance(item, dict):
                                desc = item.get("description", "No description")
                                amount_data = item.get("amount", {})
                                if isinstance(amount_data, dict):
                                    amount = amount_data.get("amount", 0)
                                else:
                                    amount = amount_data
                                print(f"  {i+1}. {desc[:50]}... - ${amount}")
                    
                    return True
                else:
                    print("No invoice data found in the response")
                    return False
                
            elif status in ("FAILED", "failed"):
                error_details = ""
                if "data" in status_data and "errorDetails" in status_data.get("data", {}):
                    error_details = status_data.get("data", {}).get("errorDetails", "")
                elif "error" in status_data:
                    error_details = status_data.get("error", "")
                    
                print(f"Extraction failed: {error_details or 'Unknown error'}")
                return False
                
            import time
            time.sleep(2)  # Wait before checking again
        
        if status != "completed":
            print(f"Extraction timed out or failed to complete. Last status: {status}")
            return False
            
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return False

if __name__ == "__main__":
    test_llama_cloud_api()