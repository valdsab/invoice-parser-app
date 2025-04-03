import os
import time
import glob
import logging
from llama_index.readers.file import PDFReader, ImageReader

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_llama_index_api():
    """
    Test the LlamaIndex API integration using PDF and Image readers.
    This is an alternative to using LlamaParse directly.
    """
    
    print("\n======== Testing LlamaIndex API Integration ========")
    
    # Check if API key is set
    api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
    if not api_key:
        print("ERROR: LLAMA_CLOUD_API_ENTOS is not set in environment variables.")
        print("Please set the API key and try again.")
        return False
    
    print(f"API key found: {api_key[:4]}...{api_key[-4:]}")
    
    # Set up the environment variable for LlamaIndex
    os.environ["LLAMA_CLOUD_API_KEY"] = api_key
    
    # Check if test file exists
    test_dir = "uploads"
    os.makedirs(test_dir, exist_ok=True)
    
    # Check if there are any existing files to test with
    pdf_files = glob.glob(os.path.join(test_dir, "*.pdf"))
    image_files = (glob.glob(os.path.join(test_dir, "*.png")) + 
                   glob.glob(os.path.join(test_dir, "*.jpg")) + 
                   glob.glob(os.path.join(test_dir, "*.jpeg")))
    
    if not pdf_files and not image_files:
        print("No test files found in 'uploads' directory.")
        print("Please add a test invoice (PDF or image) to the 'uploads' directory.")
        return False
    
    # Process PDF files if available
    if pdf_files:
        test_file_path = pdf_files[0]
        print(f"Using PDF test file: {test_file_path}")
        reader = PDFReader()
    # Otherwise process image files
    else:
        test_file_path = image_files[0]
        print(f"Using image test file: {test_file_path}")
        reader = ImageReader()
    
    # Process the file
    try:
        print("Sending file for processing...")
        print("This may take up to 60 seconds...")
        
        # Track time for informational purposes
        start_time = time.time()
        
        # Start the API request
        print("Starting document processing...")
        documents = reader.load_data(test_file_path)
        
        # Calculate elapsed time
        elapsed = time.time() - start_time
        print(f"Completed in {elapsed:.1f} seconds")
        
        if not documents or len(documents) == 0:
            print("No documents were returned from the API")
            return False
        
        # Get the first document
        doc = documents[0]
        
        print("File processed successfully")
        print(f"Document metadata: {doc.metadata}")
        print(f"Document content (sample): {doc.text[:500] if len(doc.text) > 500 else doc.text}")
        
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
    test_llama_index_api()