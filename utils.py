import os
import json
import logging
import requests
import re
import time
import urllib.request
import httpx
from app import app

# Import GroundX SDK here so it's available throughout the module
try:
    from groundx import GroundX, Document
except ImportError:
    logging.error("GroundX SDK not found. Please install it with 'pip install groundx'.")

logger = logging.getLogger(__name__)

# Timeout settings
API_REQUEST_TIMEOUT = 30  # seconds
MAX_POLLING_TIMEOUT = 25  # seconds for waiting on async operations

def clean_id(id_value):
    """
    Clean an ID value to ensure it's a proper string with no whitespace or byte prefixes.
    This prevents HTTP header errors when using IDs in API requests.
    
    Args:
        id_value: The ID value to clean (can be bytes, str, or other)
        
    Returns:
        str: A clean string representation of the ID
    """
    # Convert to string if it's bytes
    if isinstance(id_value, bytes):
        id_value = id_value.decode('utf-8', errors='ignore')
    
    # Convert to string if it's not already, strip whitespace from both ends
    # and remove any leading/trailing whitespace or special characters
    cleaned_id = str(id_value).strip()
    
    # Remove any spaces or non-visible characters that might be inside the ID
    cleaned_id = re.sub(r'\s+', '', cleaned_id)
    
    # Ensure ID is in standard UUID format if it looks like a UUID
    if re.match(r'^[0-9a-f-]{36}$', cleaned_id, re.IGNORECASE):
        # Normalize UUID format (lowercase, properly hyphenated)
        uuid_parts = cleaned_id.replace('-', '')
        if len(uuid_parts) == 32:  # Standard UUID length without hyphens
            cleaned_id = f"{uuid_parts[0:8]}-{uuid_parts[8:12]}-{uuid_parts[12:16]}-{uuid_parts[16:20]}-{uuid_parts[20:32]}"
    
    logger.debug(f"Cleaned ID from '{id_value}' to '{cleaned_id}'")
    return cleaned_id

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def parse_invoice(file_path):
    """
    Parse invoice using LlamaCloud API, with fallback to Eyelevel.ai
    
    Process:
    1. Try to parse using LlamaCloud API
    2. If LlamaCloud fails, fall back to Eyelevel.ai
    3. Return the parsed data or an error message in JSON
    
    Args:
        file_path: Path to the invoice file
        
    Returns:
        dict: Result with parsed data or error message
    """
    # First try with LlamaCloud
    llama_result = parse_invoice_with_llama_cloud(file_path)
    
    # If LlamaCloud was successful, return the result
    if llama_result.get('success'):
        logger.info("Successfully parsed invoice with LlamaCloud")
        return llama_result
    
    # If LlamaCloud failed, log the error and try with Eyelevel
    logger.warning(f"LlamaCloud parsing failed: {llama_result.get('error')}. Falling back to Eyelevel.ai.")
    eyelevel_result = parse_invoice_with_eyelevel(file_path)
    
    if eyelevel_result.get('success'):
        logger.info("Successfully parsed invoice with Eyelevel.ai (fallback)")
    else:
        logger.error(f"Both LlamaCloud and Eyelevel.ai parsing failed")
    
    return eyelevel_result


def parse_invoice_with_llama_cloud(file_path):
    """
    Parse invoice using the LlamaCloud API
    
    Process:
    1. Upload the file to LlamaCloud API
    2. Wait for processing to complete
    3. Return the parsed data or an error message in JSON
    
    Args:
        file_path: Path to the invoice file
        
    Returns:
        dict: Result with parsed data or error message
    """
    try:
        # Check if the file exists
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f"File not found: {file_path}"
            }
            
        # Get the file size
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return {
                'success': False,
                'error': "Empty file"
            }
        
        # Get the API key from environment variables
        api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
        if not api_key:
            logger.error("LLAMA_CLOUD_API_ENTOS environment variable is not set")
            return {
                'success': False,
                'error': "LlamaCloud API key not configured. Please set the LLAMA_CLOUD_API_ENTOS environment variable."
            }
        
        logger.debug(f"Parsing invoice with LlamaCloud API: {file_path}")
        
        # Get file name and type
        file_name = os.path.basename(file_path)
        file_extension = os.path.splitext(file_name)[1].lower()
        
        # Prepare headers for API calls
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Step 1: Upload file to LlamaCloud
        base_url = "https://api.llama-api.com"
        upload_url = f"{base_url}/documents/upload-url"
        
        # Get presigned URL for file upload
        logger.debug("Requesting presigned URL for file upload")
        presigned_response = requests.post(
            upload_url,
            headers=headers,
            json={"fileName": file_name},
            timeout=API_REQUEST_TIMEOUT
        )
        presigned_response.raise_for_status()
        presigned_data = presigned_response.json()
        
        upload_data = presigned_data.get("data", {})
        document_id = upload_data.get("documentId")
        presigned_url = upload_data.get("uploadUrl")
        
        if not presigned_url or not document_id:
            raise Exception(f"Invalid presigned URL response: {presigned_data}")
        
        logger.debug(f"Received presigned URL. Document ID: {document_id}")
        
        # Upload the file using the presigned URL
        with open(file_path, "rb") as file:
            file_content = file.read()
        
        logger.debug(f"Uploading file to LlamaCloud: {file_name}")
        upload_response = requests.put(
            presigned_url,
            data=file_content,
            headers={"Content-Type": "application/octet-stream"},
            timeout=API_REQUEST_TIMEOUT
        )
        upload_response.raise_for_status()
        logger.debug("File uploaded successfully")
        
        # Step 2: Process the document for invoice extraction
        process_url = f"{base_url}/documents/{document_id}/process"
        process_data = {
            "processors": ["invoice-extraction"]
        }
        
        logger.debug(f"Requesting invoice extraction for document: {document_id}")
        process_response = requests.post(
            process_url,
            headers=headers,
            json=process_data,
            timeout=API_REQUEST_TIMEOUT
        )
        process_response.raise_for_status()
        process_result = process_response.json()
        
        # Get the task ID
        task_id = process_result.get("data", {}).get("taskId")
        if not task_id:
            raise Exception(f"Invalid process response, no task ID: {process_result}")
        
        logger.debug(f"Extraction task created: {task_id}")
        
        # Step 3: Poll for task completion
        task_url = f"{base_url}/tasks/{task_id}"
        max_wait_time = MAX_POLLING_TIMEOUT
        poll_interval = 2.0
        start_time = time.time()
        
        logger.debug("Waiting for invoice extraction to complete...")
        while time.time() - start_time < max_wait_time:
            task_response = requests.get(
                task_url,
                headers=headers,
                timeout=API_REQUEST_TIMEOUT
            )
            task_response.raise_for_status()
            task_data = task_response.json().get("data", {})
            task_status = task_data.get("status")
            
            logger.debug(f"Current task status: {task_status}")
            
            if task_status == "COMPLETED":
                logger.debug("Invoice extraction completed successfully")
                break
            elif task_status in ("FAILED", "CANCELED"):
                error_details = task_data.get("errorDetails", "Unknown error")
                error_msg = f"Invoice extraction failed with status: {task_status}. Error: {error_details}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'error': error_msg
                }
            
            # Sleep briefly between checks
            time.sleep(poll_interval)
            
        # Check if we timed out
        if time.time() - start_time >= max_wait_time:
            error_msg = f"Invoice extraction timed out after {max_wait_time}s"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
        
        # Step 4: Get extraction results
        results_url = f"{base_url}/tasks/{task_id}/result"
        logger.debug(f"Retrieving extraction results for task: {task_id}")
        
        results_response = requests.get(
            results_url,
            headers=headers,
            timeout=API_REQUEST_TIMEOUT
        )
        results_response.raise_for_status()
        extraction_data = results_response.json().get("data", {})
        
        if not extraction_data:
            raise Exception("Empty extraction results received")
        
        logger.debug("Extraction results retrieved successfully")
        
        # Transform LlamaCloud data into our expected format
        transformed_data = transform_llama_cloud_to_invoice_format(extraction_data, file_name)
        
        # Use the normalize_invoice function to standardize data across different vendors
        invoice_data = normalize_invoice(transformed_data)
        
        logger.debug(f"Normalized invoice data: {json.dumps(invoice_data, indent=2)}")
        
        return {
            'success': True,
            'data': invoice_data,
            'raw_extraction_data': extraction_data  # Return the raw extraction data for reference
        }
        
    except Exception as e:
        logger.exception(f"Error parsing invoice with LlamaCloud: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def parse_invoice_with_eyelevel(file_path):
    """
    Parse invoice using the GroundX SDK (Eyelevel.ai)
    
    Process:
    1. Upload the file to a bucket
    2. Wait for ingestion to complete
    3. Return the parsed X-Ray data or an error message in JSON
    
    Args:
        file_path: Path to the invoice file
        
    Returns:
        dict: Result with parsed data or error message
    """
    
    try:
        # Check if the file exists
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f"File not found: {file_path}"
            }
            
        # Get the file size
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return {
                'success': False,
                'error': "Empty file"
            }
        
        # Get the API key from environment variables
        api_key = os.environ.get('EYELEVEL_API_KEY')
        if not api_key:
            logger.error("EYELEVEL_API_KEY environment variable is not set")
            return {
                'success': False,
                'error': "API key not configured. Please set the EYELEVEL_API_KEY environment variable."
            }
        
        logger.debug(f"Parsing invoice with GroundX SDK: {file_path}")
        
        # Get file name and type
        file_name = os.path.basename(file_path)
        file_extension = os.path.splitext(file_name)[1].lower().replace('.', '')
        
        # Initialize the GroundX client
        from groundx import GroundX, Document
        import httpx
        
        # Create a custom HTTP transport with middleware for header sanitization
        class HeaderSanitizingTransport(httpx.HTTPTransport):
            def handle_request(self, request):
                # Sanitize all header values before sending
                for name, value in list(request.headers.items()):
                    if isinstance(value, bytes):
                        # Replace with clean string value
                        clean_value = value.decode('utf-8', errors='ignore').strip()
                        clean_value = re.sub(r'\s+', '', clean_value)
                        request.headers[name] = clean_value
                    elif isinstance(value, str) and re.search(r'\s', value):
                        # Clean any strings with whitespace
                        clean_value = re.sub(r'\s+', '', value)
                        request.headers[name] = clean_value
                        
                return super().handle_request(request)

        # Create a client with our custom transport
        httpx_client = httpx.Client(transport=HeaderSanitizingTransport())
        client = GroundX(api_key=api_key, httpx_client=httpx_client)
        logger.debug("Initialized GroundX client with custom header sanitization")
        
        # STEP 1: UPLOAD THE FILE TO A BUCKET
        # Try to create bucket or use existing one
        try:
            # Try to create a new bucket specifically for invoices
            bucket_response = client.buckets.create(name="invoice_docs")
            bucket_id = clean_id(bucket_response.bucket.bucket_id)
            logger.debug(f"Created new bucket: {bucket_id}")
        except Exception as bucket_error:
            # Bucket might already exist, try to get existing buckets
            logger.debug(f"Error creating bucket, will try to use existing: {str(bucket_error)}")
            buckets_response = client.buckets.list()
            if not buckets_response.buckets:
                raise Exception("Failed to create or find any buckets")
                
            bucket_id = clean_id(buckets_response.buckets[0].bucket_id)
            logger.debug(f"Using existing bucket: {bucket_id}")
        
        # Upload file to bucket
        logger.debug(f"Uploading document to GroundX bucket: {file_path}")
        upload_response = client.ingest(
            documents=[
                Document(
                    bucket_id=bucket_id,
                    file_name=os.path.splitext(file_name)[0],  # filename without extension
                    file_path=file_path,
                    file_type=file_extension
                )
            ]
        )
        
        # STEP 2: WAIT FOR INGESTION TO COMPLETE
        process_id = clean_id(upload_response.ingest.process_id)
        logger.debug(f"Document uploaded. Process ID: {process_id}")
        
        logger.debug("Waiting for document ingestion and processing to complete...")
        max_wait_time = 25  # Maximum wait time to avoid worker timeout (30s limit)
        min_wait_time = 5   # Minimum wait time to allow initial processing
        start_time = time.time()
        poll_interval = 1.5  # Shorter interval for more responsive polling
        
        # First check status immediately
        status = client.documents.get_processing_status_by_id(process_id=process_id)
        current_status = status.ingest.status
        logger.debug(f"Initial processing status: {current_status}")
        
        # If status is already complete, we can proceed
        if current_status == "complete":
            logger.debug("Document processing completed immediately")
        else:
            # Wait for the document to finish processing
            while time.time() - start_time < max_wait_time:
                status = client.documents.get_processing_status_by_id(process_id=process_id)
                current_status = status.ingest.status
                
                logger.debug(f"Current processing status: {current_status}")
                
                if current_status == "complete":
                    logger.debug("Document processing completed successfully")
                    break
                elif current_status in ("error", "cancelled"):
                    error_msg = f"Document processing failed with status: {current_status}"
                    logger.error(error_msg)
                    return {
                        'success': False,
                        'error': error_msg
                    }
                
                # If we've waited at least the minimum time and status is still processing,
                # we'll proceed anyway and try to get what data we can
                if time.time() - start_time > min_wait_time and current_status in ("processing", "training"):
                    logger.warning(f"Proceeding with partial processing after {int(time.time() - start_time)}s - status: {current_status}")
                    break
                    
                # Sleep briefly between checks
                time.sleep(poll_interval)
            
            # If we exited the loop due to timeout, log it but try to proceed
            if time.time() - start_time >= max_wait_time and current_status not in ("complete", "error", "cancelled"):
                logger.warning(f"Document processing timeout after {max_wait_time}s, attempting to proceed with partial results")
        
        # STEP 3: RETURN THE PARSED X-RAY DATA OR ERROR MESSAGE
        # Ensure bucket_id is properly formatted before lookup
        bucket_id = clean_id(bucket_id)
        
        # Fetch document metadata from bucket
        document_response = client.documents.lookup(id=bucket_id)
        if not document_response.documents:
            raise Exception("No documents found in bucket after processing")
        
        # Get the most recently uploaded document (should be the one we just processed)
        document = document_response.documents[0]
        xray_url = document.xray_url
        
        if not xray_url:
            raise Exception("X-Ray URL not found in document metadata")
            
        logger.debug(f"Retrieving X-Ray data from: {xray_url}")
        
        # Get full X-Ray output with robust error handling
        try:
            # Use requests instead of urllib for better error handling
            response = requests.get(xray_url, timeout=30)
            
            # Check for HTTP errors
            response.raise_for_status()
            
            # Verify content type is JSON
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type.lower():
                error_preview = response.text[:200] + '...' if len(response.text) > 200 else response.text
                logger.error(f"X-Ray URL returned non-JSON response. Content-Type: {content_type}")
                logger.error(f"Response preview: {error_preview}")
                raise ValueError(f"Expected JSON response but got {content_type}. Response starts with: {error_preview[:50]}...")
            
            # Parse JSON response
            xray_data = response.json()
            
            # Validate that we got valid data with expected fields
            if not xray_data or not isinstance(xray_data, dict):
                logger.error(f"X-Ray data is not a valid dictionary: {type(xray_data)}")
                raise ValueError("Invalid X-Ray data format received")
                
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error fetching X-Ray data: {e}")
            error_preview = ""
            if hasattr(e, 'response') and e.response is not None:
                error_preview = e.response.text[:200] + '...' if len(e.response.text) > 200 else e.response.text
                logger.error(f"Error response preview: {error_preview}")
            raise Exception(f"Failed to fetch X-Ray data: HTTP {e.response.status_code if hasattr(e, 'response') and e.response is not None else 'unknown'}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching X-Ray data: {e}")
            raise Exception(f"Network error fetching X-Ray data: {str(e)}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse X-Ray JSON data: {e}")
            # Get a preview of the response if available
            error_preview = ""
            # Initialize response variable to avoid "possibly unbound" error
            response = None
            if 'response' in locals() and locals()['response'] is not None:
                response = locals()['response']
                if hasattr(response, 'text'):
                    error_preview = response.text[:200] + '...' if len(response.text) > 200 else response.text
                    logger.error(f"Invalid JSON response preview: {error_preview}")
            raise Exception(f"Failed to parse X-Ray JSON data: {str(e)}. Response preview: {error_preview[:50] if error_preview else 'N/A'}...")
        
        logger.debug("X-Ray data retrieved successfully")
        
        # Transform X-Ray data into our expected format
        transformed_data = transform_xray_to_invoice_format(xray_data, file_name)
        
        # Use the normalize_invoice function to standardize data across different vendors
        invoice_data = normalize_invoice(transformed_data)
        
        logger.debug(f"Normalized invoice data: {json.dumps(invoice_data, indent=2)}")
        
        return {
            'success': True,
            'data': invoice_data,
            'raw_xray_data': xray_data  # Return the raw X-Ray data for reference or debugging
        }
        
    except Exception as e:
        logger.exception(f"Error parsing invoice with GroundX: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def extract_from_desc(description, pattern):
    """
    Extract information from description using regex pattern
    
    Args:
        description: Text to search in
        pattern: Regex pattern to use for extraction
        
    Returns:
        str: Extracted value or None
    """
    if not description:
        return None
    
    match = re.search(pattern, description)
    return match.group(1) if match else None

def get_vendor_mapping(vendor_name, session=None):
    """
    Get vendor-specific field mappings from the database
    
    Args:
        vendor_name: The name of the vendor to look up
        session: Optional database session
        
    Returns:
        dict: Vendor field mappings or default mappings if not found
    """
    from app import db
    from models import VendorMapping
    
    # Default mapping when no custom mapping exists
    default_mapping = {
        'field_mappings': {
            'invoice_number': ['invoice_number', 'invoice #', 'invoice no', 'bill number', 'bill #', 'reference number'],
            'invoice_date': ['date', 'invoice date', 'bill date', 'issue date'],
            'due_date': ['due date', 'payment due', 'due by', 'payment due date'],
            'total_amount': ['total', 'total amount', 'amount due', 'balance due', 'grand total', 'invoice total'],
            'line_items': {
                'description': ['description', 'item', 'service', 'product', 'details'],
                'project_number': ['project number', 'project #', 'project', 'job number', 'job #', 'job code'],
                'project_name': ['project name', 'job name', 'job', 'project description'],
                'activity_code': ['activity code', 'code', 'activity', 'task code', 'service code'],
                'quantity': ['quantity', 'qty', 'units', 'hours', 'count'],
                'unit_price': ['unit price', 'rate', 'unit cost', 'price', 'cost', 'price per unit'],
                'amount': ['amount', 'total', 'line total', 'extended', 'subtotal', 'line amount'],
                'tax': ['tax', 'vat', 'gst', 'sales tax', 'tax amount']
            }
        },
        'regex_patterns': {
            'project_number': r'(?:Project|PN|Job)\s*(?:Number|#|No\.?|ID)?\s*[:=\s]\s*([A-Z0-9-]+)',
            'activity_code': r'(?:Activity|Task)\s*(?:Code|#|No\.?)?\s*[:=\s]\s*([A-Z0-9-]+)'
        }
    }
    
    try:
        if session is None:
            session = db.session
            
        # Try to find a mapping for this vendor (case-insensitive search)
        vendor_mapping = None
        
        # Exact match first
        vendor_mapping = session.query(VendorMapping).filter(
            VendorMapping.vendor_name == vendor_name,
            VendorMapping.is_active == True
        ).first()
        
        # If no exact match, try case-insensitive match
        if not vendor_mapping and vendor_name:
            vendor_mappings = session.query(VendorMapping).filter(
                VendorMapping.is_active == True
            ).all()
            
            for mapping in vendor_mappings:
                if mapping.vendor_name.lower() == vendor_name.lower():
                    vendor_mapping = mapping
                    break
        
        if vendor_mapping and vendor_mapping.field_mappings:
            try:
                # Parse the field mappings and regex patterns from JSON
                custom_mapping = {
                    'field_mappings': json.loads(vendor_mapping.field_mappings),
                    'regex_patterns': json.loads(vendor_mapping.regex_patterns) if vendor_mapping.regex_patterns else {}
                }
                
                logger.debug(f"Using custom field mapping for vendor: {vendor_name}")
                return custom_mapping
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Error parsing vendor mapping for {vendor_name}: {str(e)}")
        
        logger.debug(f"No custom mapping found for vendor: {vendor_name}, using default")
        return default_mapping
        
    except Exception as e:
        logger.exception(f"Error getting vendor mapping: {str(e)}")
        return default_mapping

def normalize_invoice(eyelevel_data):
    """
    Normalize invoice data from Eyelevel.ai response with vendor-specific mappings
    
    Args:
        eyelevel_data: Raw response data from Eyelevel.ai
        
    Returns:
        dict: Normalized invoice data with consistent fields
    """
    # Safe access helper function
    def safe(v):
        return v if v is not None else None
    
    # Get vendor name for mapping lookup
    vendor_name = safe(eyelevel_data.get('vendor', {}).get('name'))
    
    # Get vendor-specific field mappings
    mapping = get_vendor_mapping(vendor_name)
    field_mappings = mapping['field_mappings']
    regex_patterns = mapping['regex_patterns']
    
    # Create base invoice object with normalized fields
    invoice = {
        'vendor_name': vendor_name,
        'invoice_number': None,
        'invoice_date': None,
        'due_date': None,
        'total_amount': 0.0,
        'line_items': [],
        'raw_response': eyelevel_data  # Keep the raw response for debugging
    }
    
    # Apply field mappings to extract invoice header fields
    for target_field, source_fields in field_mappings.items():
        if target_field != 'line_items':  # Handle line items separately
            # Try each possible source field in order of preference
            for field in source_fields:
                value = None
                
                # Check direct property match
                if field in eyelevel_data:
                    value = eyelevel_data[field]
                
                # Check nested properties with dot notation
                elif '.' in field:
                    parts = field.split('.')
                    temp = eyelevel_data
                    valid_path = True
                    
                    for part in parts:
                        if isinstance(temp, dict) and part in temp:
                            temp = temp[part]
                        else:
                            valid_path = False
                            break
                    
                    if valid_path:
                        value = temp
                
                # If we found a value, use it and break the loop
                if value is not None and value != '':
                    invoice[target_field] = value
                    break
    
    # Ensure numeric value for total_amount
    try:
        invoice['total_amount'] = float(invoice.get('total_amount', 0) or 0)
    except (ValueError, TypeError):
        # If conversion fails, try to extract numeric portion
        if isinstance(invoice.get('total_amount'), str):
            amount_str = ''.join(c for c in invoice['total_amount'] if c.isdigit() or c == '.')
            try:
                invoice['total_amount'] = float(amount_str) if amount_str else 0.0
            except (ValueError, TypeError):
                invoice['total_amount'] = 0.0
        else:
            invoice['total_amount'] = 0.0
    
    # Process line items with consistent field structure
    if eyelevel_data.get('line_items') and isinstance(eyelevel_data['line_items'], list):
        line_item_mappings = field_mappings.get('line_items', {})
        
        for item in eyelevel_data['line_items']:
            line_item = {
                'description': '',
                'project_number': '',
                'project_name': '',
                'activity_code': '',
                'quantity': 1.0,
                'unit_price': 0.0,
                'amount': 0.0,
                'tax': 0.0
            }
            
            # Apply field mappings for line items
            for target_field, source_fields in line_item_mappings.items():
                for field in source_fields:
                    if field in item and item[field] is not None and item[field] != '':
                        # Store the value
                        line_item[target_field] = item[field]
                        break
            
            # Extract data from description using regex if available
            description = line_item.get('description') or ''
            
            # Apply custom regex patterns to extract information from description
            for field, pattern in regex_patterns.items():
                if not line_item.get(field) and description:
                    extracted = extract_from_desc(description, pattern)
                    if extracted:
                        line_item[field] = extracted
            
            # Fallback for missing project number
            if not line_item['project_number'] and description:
                line_item['project_number'] = extract_from_desc(description, r'PN:?\s*(\d+)')
            
            # Ensure numeric values
            for field in ['quantity', 'unit_price', 'amount', 'tax']:
                try:
                    line_item[field] = float(line_item[field] or 0)
                except (ValueError, TypeError):
                    line_item[field] = 0.0
            
            invoice['line_items'].append(line_item)
    
    logger.debug(f"Normalized invoice data: {json.dumps(invoice, indent=2)}")
    return invoice

def transform_llama_cloud_to_invoice_format(extraction_data, file_name):
    """
    Transform LlamaCloud extraction data into a format compatible with our invoice model
    
    Args:
        extraction_data: The extraction data from LlamaCloud API
        file_name: The original file name of the invoice
        
    Returns:
        dict: Transformed data in a format expected by normalize_invoice()
    """
    try:
        logger.debug(f"Transforming LlamaCloud extraction data for: {file_name}")
        
        # Get the invoice extraction results
        invoice_data = extraction_data.get("invoice", {})
        if not invoice_data:
            raise ValueError("No invoice data found in extraction results")
            
        # Extract vendor info
        vendor_name = invoice_data.get("vendor", {}).get("name", "Unknown Vendor")
        
        # Extract invoice metadata
        invoice_number = invoice_data.get("invoiceNumber", "")
        invoice_date = invoice_data.get("invoiceDate", "")
        due_date = invoice_data.get("dueDate", "")
        total_amount = invoice_data.get("totalAmount", {}).get("amount", 0)
        
        # Extract line items
        line_items_data = invoice_data.get("lineItems", [])
        line_items = []
        
        for item in line_items_data:
            # Extract line item fields
            description = item.get("description", "")
            quantity = item.get("quantity", 0)
            unit_price = item.get("unitPrice", {}).get("amount", 0)
            amount = item.get("amount", {}).get("amount", 0)
            tax = item.get("tax", {}).get("amount", 0)
            
            # Look for project number and activity code in the description
            project_number = None
            project_name = None
            activity_code = None
            
            # Attempt to extract project number and activity code using regex patterns
            if description:
                project_number_pattern = r'(?:Project|PN|Job)\s*(?:Number|#|No\.?|ID)?\s*[:=\s]\s*([A-Z0-9-]+)'
                activity_code_pattern = r'(?:Activity|Task)\s*(?:Code|#|No\.?)?\s*[:=\s]\s*([A-Z0-9-]+)'
                
                project_number_match = re.search(project_number_pattern, description)
                if project_number_match:
                    project_number = project_number_match.group(1)
                
                activity_code_match = re.search(activity_code_pattern, description)
                if activity_code_match:
                    activity_code = activity_code_match.group(1)
            
            # Create line item
            line_item = {
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": amount,
                "tax": tax,
                "project_number": project_number,
                "project_name": project_name,
                "activity_code": activity_code
            }
            
            line_items.append(line_item)
        
        # Assemble the transformed data
        transformed_data = {
            "vendor_name": vendor_name,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "total_amount": total_amount,
            "file_name": file_name,
            "line_items": line_items
        }
        
        logger.debug(f"Successfully transformed LlamaCloud data for: {file_name}")
        return transformed_data
        
    except Exception as e:
        logger.exception(f"Error transforming LlamaCloud data: {str(e)}")
        # Return minimal data structure to prevent further errors
        return {
            "vendor_name": "Unknown",
            "invoice_number": "",
            "invoice_date": "",
            "due_date": "",
            "total_amount": 0,
            "file_name": file_name,
            "line_items": []
        }


def transform_xray_to_invoice_format(xray_data, file_name):
    """
    Transform X-Ray data from GroundX into a format compatible with our invoice model
    
    Args:
        xray_data: The X-Ray JSON data from GroundX
        file_name: The original file name of the invoice
        
    Returns:
        dict: Transformed data in a format expected by normalize_invoice()
    """
    logger.debug("Transforming X-Ray data to invoice format")
    
    # Initialize the transformed data structure
    transformed_data = {
        "vendor": {
            "name": ""
        },
        "invoice_number": "",
        "date": "",
        "due_date": "",
        "total_amount": "0",
        "line_items": [],
        "file_keywords": xray_data.get("fileKeywords", ""),
        "file_summary": xray_data.get("fileSummary", "")
    }
    
    try:
        # Extract main invoice metadata first
        pages = xray_data.get("documentPages", [])
        if not pages:
            logger.warning("No document pages found in X-Ray data")
            return transformed_data
            
        # Process each page for invoice metadata and line items
        for page in pages:
            # Extract invoice metadata from chunks
            for chunk in page.get("chunks", []):
                chunk_type = chunk.get("chunkType", "").lower()
                content_type = chunk.get("contentType", [])
                text = chunk.get("text", "")  # Direct text access
                
                # If no direct text, look in content
                if not text and "content" in chunk and "text" in chunk["content"]:
                    text = chunk["content"]["text"]
                
                # Extract metadata based on chunk type
                if any(vendor_type in chunk_type for vendor_type in ["vendor", "supplier", "seller"]):
                    transformed_data["vendor"]["name"] = text
                
                elif any(inv_num in chunk_type for inv_num in ["invoice number", "invoice #", "bill number"]):
                    transformed_data["invoice_number"] = text
                
                elif any(date_type in chunk_type for date_type in ["invoice date", "date", "issue date"]):
                    transformed_data["date"] = text
                
                elif any(due_type in chunk_type for due_type in ["due date", "payment due"]):
                    transformed_data["due_date"] = text
                
                elif any(total in chunk_type for total in ["total", "amount due", "balance due", "grand total"]):
                    # Remove any non-numeric characters except decimal point
                    amount = ''.join(c for c in text if c.isdigit() or c == '.')
                    if amount:
                        transformed_data["total_amount"] = amount
                        
                # Extract line items from tables
                if "table" in content_type:
                    # Process structured table data if available
                    if "json" in chunk:
                        for row in chunk["json"]:
                            # Normalize field names (case-insensitive)
                            normalized_row = {k.lower(): v for k, v in row.items()}
                            
                            # Extract line item fields with multiple possible key names
                            line_item = {
                                "description": get_first_value(normalized_row, ["description", "item", "service", "product"]),
                                "project_number": get_first_value(normalized_row, ["project number", "project #", "project", "job number", "job #"]),
                                "project_name": get_first_value(normalized_row, ["project name", "job name", "job"]),
                                "activity_code": get_first_value(normalized_row, ["activity code", "code", "activity", "task code"]),
                                "quantity": get_first_value(normalized_row, ["quantity", "qty", "units", "hours"]) or "1",
                                "unit_price": get_first_value(normalized_row, ["unit price", "rate", "unit cost", "price", "cost"]) or "0",
                                "amount": get_first_value(normalized_row, ["amount", "total", "line total", "extended", "subtotal"]) or "0",
                                "tax": get_first_value(normalized_row, ["tax", "vat", "gst", "sales tax"]) or "0"
                            }
                            
                            # Ensure numeric fields are strings for consistent handling
                            for field in ["quantity", "unit_price", "amount", "tax"]:
                                if line_item[field] is not None and not isinstance(line_item[field], str):
                                    line_item[field] = str(line_item[field])
                            
                            transformed_data["line_items"].append(line_item)
                
                # Fallback to semi-structured or narrative content for line items
                elif any(item_type in chunk_type for item_type in ["line item", "service item", "product item"]):
                    # Use narrative or text content if available
                    description = text
                    
                    # Extract potential project number using regex
                    project_number = extract_from_desc(description, r'(?:Project|PN|Job)\s*(?:Number|#|No\.?|ID)?\s*[:=\s]\s*([A-Z0-9-]+)')
                    
                    # Extract activity code using regex
                    activity_code = extract_from_desc(description, r'(?:Activity|Task)\s*(?:Code|#|No\.?)?\s*[:=\s]\s*([A-Z0-9-]+)')
                    
                    # Create line item with available information
                    line_item = {
                        "description": description,
                        "project_number": project_number or "",
                        "project_name": "",  # Often not available in narrative form
                        "activity_code": activity_code or "",
                        "quantity": "1",  # Default values
                        "unit_price": "0",
                        "amount": "0",
                        "tax": "0"
                    }
                    
                    # Try to extract detailed line item fields if available
                    if "details" in chunk:
                        details = chunk["details"]
                        if "quantity" in details:
                            line_item["quantity"] = str(details["quantity"])
                        if "unitPrice" in details or "rate" in details:
                            line_item["unit_price"] = str(details.get("unitPrice") or details.get("rate", 0))
                        if "amount" in details or "total" in details:
                            line_item["amount"] = str(details.get("amount") or details.get("total", 0))
                        if "tax" in details:
                            line_item["tax"] = str(details["tax"])
                    
                    transformed_data["line_items"].append(line_item)
        
        # Fallback for vendor name if not found
        if not transformed_data["vendor"]["name"]:
            # Try to extract from file_summary or use filename
            if transformed_data["file_summary"]:
                # Look for vendor/supplier mentions in summary
                vendor_match = re.search(r'(?:from|by|vendor|supplier)[\s:]+([A-Za-z0-9\s&.,]+?)(?:to|for|invoice|on|dated)', 
                                        transformed_data["file_summary"], re.IGNORECASE)
                if vendor_match:
                    transformed_data["vendor"]["name"] = vendor_match.group(1).strip()
                else:
                    # Just use the first part of summary as it often starts with vendor name
                    transformed_data["vendor"]["name"] = transformed_data["file_summary"].split(",")[0].strip()
            else:
                # Extract potential vendor name from filename
                filename_parts = os.path.splitext(file_name)[0].split('_')
                if len(filename_parts) > 1:
                    transformed_data["vendor"]["name"] = filename_parts[0].replace('-', ' ').title()
        
        # If we still don't have an invoice number, use the filename
        if not transformed_data["invoice_number"]:
            transformed_data["invoice_number"] = os.path.splitext(file_name)[0]
        
        logger.debug(f"Transformed data: {json.dumps(transformed_data, indent=2)}")
        return transformed_data
        
    except Exception as e:
        logger.exception(f"Error transforming X-Ray data: {str(e)}")
        # Return basic structure with information from filename
        return {
            "vendor": {"name": "Unknown Vendor"},
            "invoice_number": os.path.splitext(file_name)[0],
            "date": "",
            "due_date": "",
            "total_amount": "0",
            "line_items": [
                {
                    "description": f"Error extracting line items: {str(e)}",
                    "quantity": "1",
                    "unit_price": "0",
                    "amount": "0",
                    "tax": "0"
                }
            ]
        }

def get_first_value(data_dict, possible_keys):
    """
    Get the first non-empty value from a dictionary using a list of possible keys
    
    Args:
        data_dict: Dictionary to search in
        possible_keys: List of possible keys to try in order
        
    Returns:
        The first non-empty value found or None if no matches
    """
    for key in possible_keys:
        if key in data_dict and data_dict[key]:
            return data_dict[key]
    return None

def create_zoho_vendor_bill(invoice, line_items):
    """
    Simulated function to create a vendor bill in Zoho Books
    (Actual Zoho Books integration will be implemented later)
    
    Args:
        invoice: Invoice model object
        line_items: List of line item dictionaries
        
    Returns:
        dict: Result with vendor bill ID or error message
    """
    try:
        logger.debug(f"Creating simulated vendor bill for invoice {invoice.id}")
        
        # Log what would be sent to Zoho
        vendor_bill_data = {
            "vendor_name": invoice.vendor_name,
            "bill_number": invoice.invoice_number,
            "date": invoice.invoice_date.strftime('%Y-%m-%d') if invoice.invoice_date else None,
            "due_date": invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else None,
            "total": invoice.total_amount,
            "line_items": []
        }
        
        # Add line items
        for item in line_items:
            line_item = {
                "name": item.get('description'),
                "quantity": item.get('quantity'),
                "rate": item.get('unit_price'),
                "tax": item.get('tax', 0)
            }
            vendor_bill_data["line_items"].append(line_item)
        
        logger.debug(f"Would send to Zoho: {json.dumps(vendor_bill_data, indent=2)}")
        
        # Simulate a successful response
        vendor_bill_id = f"VB-{invoice.id}-{int(invoice.total_amount)}"
        
        return {
            'success': True,
            'vendor_bill_id': vendor_bill_id
        }
        
    except Exception as e:
        logger.exception(f"Error creating vendor bill in Zoho: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
