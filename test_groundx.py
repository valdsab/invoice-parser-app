import os
import json
import logging
from utils import parse_invoice_with_llama_cloud, parse_invoice  # Use both functions

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_llama_cloud_integration():
    """
    Test the LlamaCloud API integration to make sure it:
    1. Uploads a file to the API
    2. Processes the document
    3. Returns parsed invoice data or an error message
    """
    
    print("\n======== Testing LlamaCloud Integration ========")
    
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
    
    test_file = os.path.join(test_dir, test_files[0])
    print(f"Using test file: {test_file}")
    
    # Process the file with LlamaCloud directly
    print("Sending file directly to LlamaCloud for processing...")
    result = parse_invoice_with_llama_cloud(test_file)
    
    # If direct API call fails, try through the wrapper
    if not result['success']:
        print(f"Direct API call failed: {result.get('error')}")
        print("Trying through the wrapper function...")
        result = parse_invoice(test_file)
    
    # Check result
    if result['success']:
        print("\n✅ SUCCESS: File processed successfully")
        
        # Display normalized invoice data
        invoice_data = result['data']
        print("\nExtracted Invoice Data:")
        print(f"Vendor: {invoice_data.get('vendor_name')}")
        print(f"Invoice #: {invoice_data.get('invoice_number')}")
        print(f"Date: {invoice_data.get('invoice_date')}")
        print(f"Total: ${invoice_data.get('total_amount')}")
        
        # Display line items if available
        line_items = invoice_data.get('line_items', [])
        if line_items:
            print(f"\nLine Items ({len(line_items)}):")
            for i, item in enumerate(line_items):
                print(f"  {i+1}. {item.get('description')[:50]}... - ${item.get('amount')}")
        
        # Confirm raw extraction data is available
        raw_data = result.get('raw_extraction_data', {})
        if raw_data:
            print(f"\nRaw extraction data contains {len(json.dumps(raw_data))} characters")
            if isinstance(raw_data, dict):
                print("Raw data keys: " + ", ".join(raw_data.keys()))
        else:
            print("\nWARNING: No raw extraction data returned")
            
        return True
    else:
        print(f"\n❌ ERROR: {result.get('error')}")
        return False

if __name__ == "__main__":
    test_llama_cloud_integration()