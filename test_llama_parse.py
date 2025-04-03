import os
import logging
import time
import sys
from llama_parse import LlamaParse
import glob

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_llama_parse_api():
    """
    Test the LlamaParse API integration using the official SDK.
    
    This avoids manual API endpoint construction and handles
    authentication automatically.
    """
    
    print("\n======== Testing LlamaParse API with SDK ========")
    
    # Check if API key is set
    api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
    if not api_key:
        print("ERROR: LLAMA_CLOUD_API_ENTOS is not set in environment variables.")
        print("Please set the API key and try again.")
        return False
    
    print(f"API key found: {api_key[:4]}...{api_key[-4:]}")
    
    # Initialize the LlamaParse client
    try:
        llama_parse = LlamaParse(api_key=api_key)
        print("Successfully initialized LlamaParse client")
    except Exception as e:
        print(f"Failed to initialize LlamaParse client: {str(e)}")
        return False
    
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
    
    # Process the file with LlamaParse
    try:
        print("Sending file to LlamaParse for processing...")
        print("This may take up to 60 seconds...")
        
        # Track time for informational purposes
        start_time = time.time()
        
        # Start the API request
        print("Starting API request...")
        documents = llama_parse.load_data(test_file_path)
        
        # Calculate elapsed time
        elapsed = time.time() - start_time
        print(f"Completed in {elapsed:.1f} seconds")
        
        if not documents or len(documents) == 0:
            print("No documents were returned from the API")
            return False
        
        # Get the first document
        result = documents[0]
        
        print("File processed successfully")
        print(f"Document metadata: {result.metadata if hasattr(result, 'metadata') else 'No metadata'}")
        print(f"Document content (sample): {result.text[:500] if hasattr(result, 'text') else 'No text found'}")
        
        # Check if there are any extracted tables
        if hasattr(result, 'tables') and result.tables:
            print(f"Extracted {len(result.tables)} tables from document")
            for i, table in enumerate(result.tables):
                print(f"Table {i+1} dimensions: {len(table)} rows")
                if table:
                    print(f"Table header: {list(table[0].keys())}")
        else:
            print("No tables extracted from document")
        
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
    test_llama_parse_api()