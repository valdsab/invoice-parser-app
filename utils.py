import os
import json
import logging
import requests
import re
import time
import urllib.request
from app import app

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

def allowed_file(filename, mime_type=None):
    """
    Check if file extension and MIME type are allowed
    
    Args:
        filename: The name of the file to check
        mime_type: Optional MIME type to validate
        
    Returns:
        bool: True if the file is allowed, False otherwise
    """
    # Validate file extension
    if not ('.' in filename and \
            filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']):
        logger.warning(f"Rejected file with invalid extension: {filename}")
        return False
    
    # Validate MIME type if provided
    if mime_type:
        allowed_mime_types = {
            'application/pdf': ['pdf'],
            'image/jpeg': ['jpg', 'jpeg'],
            'image/png': ['png']
        }
        
        # Check if the MIME type is allowed
        if mime_type not in allowed_mime_types:
            logger.warning(f"Rejected file with invalid MIME type: {mime_type}")
            return False
        
        # Check if the file extension matches the MIME type
        extension = filename.rsplit('.', 1)[1].lower()
        if extension not in allowed_mime_types.get(mime_type, []):
            logger.warning(f"Rejected file with mismatched MIME type and extension: {mime_type}, {extension}")
            return False
    
    return True

def parse_invoice(file_path):
    """
    Parse invoice using LlamaCloud API
    
    Process:
    1. Try to parse using LlamaCloud API
    2. Return the parsed data or an error message in JSON
    
    Args:
        file_path: Path to the invoice file
        
    Returns:
        dict: Result with parsed data or error message
    """
    parser_used = "LlamaCloud"
    
    try:
        logger.debug(f"=== STARTING INVOICE PARSING: {file_path} ===")
        
        # Check if the API key exists
        api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
        if not api_key:
            logger.error("LLAMA_CLOUD_API_ENTOS environment variable is not set")
            return {
                'success': False,
                'error': "LlamaCloud API key not configured. Please set the LLAMA_CLOUD_API_ENTOS environment variable.",
                'parser_used': parser_used
            }
        
        # Parse with LlamaCloud
        logger.info(f"Parsing invoice with LlamaCloud: {file_path}")
        result = parse_invoice_with_llama_cloud(file_path)
        
        # Add which parser was used
        result['parser_used'] = parser_used
        
        # Validate parse result structure
        if not isinstance(result, dict):
            logger.error(f"Invalid parse result type: {type(result)}")
            return {
                'success': False,
                'error': f"Invalid parse result format: expected dictionary, got {type(result)}",
                'parser_used': parser_used
            }
        
        # Check if parsing was successful
        if result.get('success'):
            logger.info("Successfully parsed invoice with LlamaCloud")
            logger.debug("Validating parse result data structure")
            
            # Check if we have data
            if 'data' not in result:
                logger.error("Successful parse result missing 'data' field")
                return {
                    'success': False,
                    'error': "Invalid parse result: missing data field",
                    'parser_used': parser_used
                }
                
            # Check if we have raw extraction data
            if 'raw_extraction_data' not in result:
                logger.warning("Successful parse result missing 'raw_extraction_data' field")
                # Not a fatal error, will continue
            
            # Validate data keys
            data = result.get('data', {})
            if not isinstance(data, dict):
                logger.error(f"Invalid 'data' type: {type(data)}")
                return {
                    'success': False,
                    'error': f"Invalid data format: expected dictionary, got {type(data)}",
                    'parser_used': parser_used
                }
                
            # Check for required fields in data
            required_fields = ['vendor_name', 'invoice_number', 'invoice_date', 'total_amount', 'line_items']
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                logger.warning(f"Parse result missing required fields: {missing_fields}")
                # Not a fatal error, will continue with nulls
            
            # Check line items if they exist
            if 'line_items' in data and not isinstance(data['line_items'], list):
                logger.error(f"Invalid 'line_items' type: {type(data['line_items'])}")
                return {
                    'success': False,
                    'error': f"Invalid line_items format: expected list, got {type(data['line_items'])}",
                    'parser_used': parser_used
                }
                
            logger.debug(f"=== COMPLETED INVOICE PARSING SUCCESSFULLY: {file_path} ===")
        else:
            # Log error
            error_msg = result.get('error', 'Unknown error with LlamaCloud')
            logger.error(f"LlamaCloud parsing failed: {error_msg}")
        
        return result
            
    except Exception as e:
        # Catch any exception that might occur during parsing
        error_msg = str(e)
        logger.exception(f"=== CRITICAL ERROR PARSING INVOICE: {error_msg} ===")
        
        return {
            'success': False,
            'error': f"Invoice parsing failed: {error_msg}",
            'parser_used': parser_used
        }


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
        
        # Step 1: Upload file to LlamaCloud using the API that works in our tests
        base_url = "https://api.cloud.llamaindex.ai"
        upload_url = f"{base_url}/api/parsing/upload"
        
        logger.debug(f"Uploading file to LlamaCloud: {file_name}")
        
        # Read the file
        with open(file_path, "rb") as file:
            file_content = file.read()
        
        # Determine MIME type based on file extension
        mime_type = 'application/pdf'
        if file_extension.lower() in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif file_extension.lower() == '.png':
            mime_type = 'image/png'
            
        # Use multipart/form-data upload
        files = {
            'file': (file_name, file_content, mime_type)
        }
        
        # Headers for multipart upload - no content-type here, requests will set it
        upload_headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        
        # Send upload request with files parameter for multipart/form-data
        upload_response = requests.post(
            upload_url,
            headers=upload_headers,
            files=files,
            timeout=API_REQUEST_TIMEOUT
        )
        upload_response.raise_for_status()
        
        # Get the job ID
        upload_data = upload_response.json()
        job_id = upload_data.get("id")
        
        if not job_id:
            raise Exception(f"No job ID returned from upload request: {upload_data}")
        
        job_status = upload_data.get("status")
        logger.debug(f"Upload successful. Job ID: {job_id}, Status: {job_status}")
        
        # Step 2: Poll for job completion
        status_url = f"{base_url}/api/parsing/job/{job_id}"
        max_wait_time = MAX_POLLING_TIMEOUT
        poll_interval = 2.0
        start_time = time.time()
        
        logger.debug("Waiting for invoice extraction to complete...")
        
        status_data = None
        while time.time() - start_time < max_wait_time:
            status_response = requests.get(
                status_url,
                headers=upload_headers,  # Use the headers without Content-Type
                timeout=API_REQUEST_TIMEOUT
            )
            status_response.raise_for_status()
            status_data = status_response.json()
            
            job_status = status_data.get("status")
            logger.debug(f"Current job status: {job_status}")
            
            # Check if processing is complete
            if job_status in ["COMPLETE", "SUCCESS", "success"]:
                logger.debug("Invoice extraction completed successfully")
                break
            
            # Check for error
            if job_status in ["ERROR", "error", "FAILED", "failed"]:
                error_msg = f"Invoice extraction failed: {status_data.get('error', 'Unknown error')}"
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
        
        # Step 3: Get extraction results (already in status_data)
        logger.debug("Retrieving extraction results")
        
        # The extraction data is already in the status response
        extraction_data = status_data
        
        if not extraction_data:
            raise Exception("Empty extraction results received")
        
        # Log the raw response for debugging
        try:
            logger.debug("LlamaCloud Raw Response: %s", json.dumps(extraction_data, indent=2))
        except Exception as e:
            logger.error(f"Could not serialize LlamaCloud response for logging: {str(e)}")
            logger.debug(f"LlamaCloud Raw Response Type: {type(extraction_data)}, Content preview: {str(extraction_data)[:500]}")
        
        logger.debug("Extraction results retrieved successfully")
        
        # Transform LlamaCloud data into our expected format
        try:
            transformed_data = transform_llama_cloud_to_invoice_format(extraction_data, file_name)
            if not transformed_data:
                logger.error("Failed to transform LlamaCloud data - no result returned")
                return {
                    'success': False,
                    'error': "Failed to transform LlamaCloud extraction data",
                    'raw_extraction_data': extraction_data
                }
                
            logger.debug(f"Successfully transformed LlamaCloud data with keys: {list(transformed_data.keys()) if isinstance(transformed_data, dict) else 'not a dict'}")
            
            # Use the normalize_invoice function to standardize data across different vendors
            invoice_data = normalize_invoice(transformed_data)
            if not invoice_data:
                logger.error("Failed to normalize transformed data - no result returned")
                return {
                    'success': False,
                    'error': "Failed to normalize invoice data",
                    'raw_extraction_data': extraction_data,
                    'transformed_data': transformed_data
                }
                
            logger.debug(f"Normalized invoice data: {json.dumps(invoice_data, indent=2)}")
            
            # Verify we have at least some data to work with
            if (not invoice_data.get('vendor_name') and 
                not invoice_data.get('invoice_number') and 
                not invoice_data.get('invoice_date') and 
                not invoice_data.get('total_amount')):
                logger.warning("All critical invoice fields are empty after normalization")
                # We'll still return success with empty data, but log a warning
            
            return {
                'success': True,
                'data': invoice_data,
                'raw_extraction_data': extraction_data  # Return the raw extraction data for reference
            }
            
        except Exception as e:
            logger.exception(f"Error during transformation or normalization: {str(e)}")
            return {
                'success': False,
                'error': f"Error processing extraction results: {str(e)}",
                'raw_extraction_data': extraction_data  # Return the raw data anyway for diagnostic purposes
            }
        
    except Exception as e:
        logger.exception(f"Error parsing invoice with LlamaCloud: {str(e)}")
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

def normalize_invoice(invoice_data):
    """
    Normalize invoice data from LlamaCloud response with vendor-specific mappings
    
    Args:
        invoice_data: Raw response data from LlamaCloud
        
    Returns:
        dict: Normalized invoice data with consistent fields
    """
    # Safe access helper function
    def safe(v):
        return v if v is not None else None
    
    # Get vendor name for mapping lookup - handle different possible structures
    vendor_name = None
    
    # Try multiple possible paths to find the vendor name
    if isinstance(invoice_data, dict):
        # Direct vendor_name field
        if 'vendor_name' in invoice_data and invoice_data['vendor_name']:
            vendor_name = invoice_data['vendor_name']
            logger.debug(f"Found vendor_name directly: {vendor_name}")
        
        # Nested in vendor object
        elif 'vendor' in invoice_data:
            vendor = invoice_data['vendor']
            if isinstance(vendor, dict) and 'name' in vendor:
                vendor_name = vendor['name']
                logger.debug(f"Found vendor.name: {vendor_name}")
            elif isinstance(vendor, str):
                vendor_name = vendor
                logger.debug(f"Found vendor as string: {vendor_name}")
    
    logger.debug(f"Using vendor name for mapping: {vendor_name}")
    
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
        'raw_response': invoice_data  # Keep the raw response for debugging
    }
    
    # Apply field mappings to extract invoice header fields
    for target_field, source_fields in field_mappings.items():
        if target_field != 'line_items':  # Handle line items separately
            # Try each possible source field in order of preference
            for field in source_fields:
                value = None
                
                # Check direct property match
                if field in invoice_data:
                    value = invoice_data[field]
                
                # Check nested properties with dot notation
                elif '.' in field:
                    parts = field.split('.')
                    temp = invoice_data
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
    if invoice_data.get('line_items') and isinstance(invoice_data['line_items'], list):
        line_item_mappings = field_mappings.get('line_items', {})
        
        for item in invoice_data['line_items']:
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
        
        # Log the structure of the extraction_data
        logger.debug(f"Extraction data type: {type(extraction_data)}")
        if isinstance(extraction_data, dict):
            logger.debug(f"Extraction data keys: {list(extraction_data.keys())}")
            
            # LlamaCloud/LlamaParse often puts the actual data in a 'data' or 'document' field
            for potential_key in ['data', 'document', 'results', 'content', 'extraction']:
                if potential_key in extraction_data and extraction_data[potential_key]:
                    logger.debug(f"Found potential data in '{potential_key}' field")
                    if isinstance(extraction_data[potential_key], dict):
                        extraction_data = extraction_data[potential_key]
                        logger.debug(f"Using '{potential_key}' as root. New keys: {list(extraction_data.keys())}")
                        break
        else:
            logger.debug(f"Extraction data is not a dictionary: {str(extraction_data)[:200]}")
            # Early return with empty data if we don't have a dictionary
            if not isinstance(extraction_data, dict):
                logger.error("Cannot process non-dictionary extraction data")
                raise ValueError(f"Extraction data must be a dictionary, got {type(extraction_data)}")
        
        # Analyze document structure in more detail to help find key fields
        def recursive_explore_dict(data, prefix="", max_depth=3, depth=0):
            """Recursively explore dictionary structure to identify fields"""
            if depth >= max_depth:
                return
                
            if isinstance(data, dict):
                for key, value in data.items():
                    path = f"{prefix}.{key}" if prefix else key
                    value_type = type(value).__name__
                    value_preview = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                    logger.debug(f"Field: {path} ({value_type}) = {value_preview}")
                    recursive_explore_dict(value, path, max_depth, depth + 1)
            elif isinstance(data, list) and len(data) > 0:
                logger.debug(f"List at {prefix} with {len(data)} items")
                if len(data) > 0:
                    recursive_explore_dict(data[0], f"{prefix}[0]", max_depth, depth + 1)
        
        logger.debug("Exploring extraction data structure:")
        recursive_explore_dict(extraction_data)
        
        # Get the invoice extraction results
        invoice_data = extraction_data
        
        # Look for invoice properties in expected locations
        vendor_info = None
        vendor_name = None
        
        # Try to extract vendor information from various possible fields
        vendor_paths = [
            # Direct paths
            ("vendor", "name"),
            ("vendor_name",),
            ("metadata", "vendor"),
            ("metadata", "vendor_name"),
            ("header", "vendor"),
            ("header", "vendor_name"),
            ("supplier", "name"),
            ("supplier_name",),
            ("from",),
            # Check directly in root
            ("seller",),
            ("seller_name",),
            ("biller",),
            ("biller_name",),
            ("company",),
            ("company_name",),
            ("from_company",),
        ]
        
        # Try each potential path
        for path in vendor_paths:
            temp = invoice_data
            valid_path = True
            
            for part in path:
                if isinstance(temp, dict) and part in temp:
                    temp = temp[part]
                else:
                    valid_path = False
                    break
            
            if valid_path and temp:
                vendor_name = temp
                logger.debug(f"Found vendor name '{vendor_name}' using path {path}")
                break
        
        # If still no vendor name, try looking in text content
        if not vendor_name:
            for key in ["text", "full_text", "content", "raw_text"]:
                if key in invoice_data and invoice_data[key]:
                    # Try first 5 lines for company name
                    text = invoice_data[key]
                    if isinstance(text, str):
                        lines = text.split('\n')[:5]
                        if lines:
                            vendor_name = lines[0].strip()
                            logger.debug(f"Using first line of text content as vendor name: '{vendor_name}'")
                            break
        
        # Extract invoice metadata - try different possible field names
        invoice_number_paths = [
            ("invoice_number",),
            ("invoiceNumber",),
            ("invoice", "number"),
            ("header", "invoice_number"),
            ("metadata", "invoice_number"),
            ("id",),
            ("invoice_id",),
            ("document_number",),
            ("number",),
        ]
        
        invoice_number = None
        for path in invoice_number_paths:
            temp = invoice_data
            valid_path = True
            
            for part in path:
                if isinstance(temp, dict) and part in temp:
                    temp = temp[part]
                else:
                    valid_path = False
                    break
            
            if valid_path and temp:
                invoice_number = str(temp)
                logger.debug(f"Found invoice number '{invoice_number}' using path {path}")
                break
        
        # Extract dates with similar approach
        invoice_date_paths = [
            ("invoice_date",),
            ("invoiceDate",),
            ("date",),
            ("issue_date",),
            ("header", "date"),
            ("header", "invoice_date"),
            ("metadata", "date"),
            ("metadata", "invoice_date"),
        ]
        
        due_date_paths = [
            ("due_date",),
            ("dueDate",),
            ("payment_due",),
            ("payment_due_date",),
            ("header", "due_date"),
            ("metadata", "due_date"),
        ]
        
        invoice_date = None
        for path in invoice_date_paths:
            temp = invoice_data
            valid_path = True
            
            for part in path:
                if isinstance(temp, dict) and part in temp:
                    temp = temp[part]
                else:
                    valid_path = False
                    break
            
            if valid_path and temp:
                invoice_date = str(temp)
                logger.debug(f"Found invoice date '{invoice_date}' using path {path}")
                break
        
        due_date = None
        for path in due_date_paths:
            temp = invoice_data
            valid_path = True
            
            for part in path:
                if isinstance(temp, dict) and part in temp:
                    temp = temp[part]
                else:
                    valid_path = False
                    break
            
            if valid_path and temp:
                due_date = str(temp)
                logger.debug(f"Found due date '{due_date}' using path {path}")
                break
        
        # Extract total amount - handle different formats
        total_amount = 0
        amount_paths = [
            ("total_amount",),
            ("totalAmount",),
            ("total",),
            ("amount",),
            ("grand_total",),
            ("invoice_total",),
            ("header", "total_amount"),
            ("header", "total"),
            ("summary", "total"),
            ("summary", "amount"),
        ]
        
        for path in amount_paths:
            temp = invoice_data
            valid_path = True
            
            for part in path:
                if isinstance(temp, dict) and part in temp:
                    temp = temp[part]
                else:
                    valid_path = False
                    break
            
            if valid_path:
                # Handle different formats of amount data
                if isinstance(temp, dict) and "amount" in temp:
                    total_amount = temp.get("amount", 0)
                elif isinstance(temp, (int, float)):
                    total_amount = temp
                elif isinstance(temp, str):
                    # Try to convert string to float, removing currency symbols
                    amount_str = ''.join(c for c in temp if c.isdigit() or c == '.')
                    try:
                        total_amount = float(amount_str) if amount_str else 0
                    except:
                        total_amount = 0
                        
                logger.debug(f"Found total amount '{total_amount}' using path {path}")
                break
        
        # Extract line items - check multiple possible locations and formats
        line_items = []
        line_item_paths = [
            ("line_items",),
            ("lineItems",),
            ("items",),
            ("details",),
            ("invoice_items",),
            ("invoice_lines",),
            ("lines",),
        ]
        
        line_items_data = []
        for path in line_item_paths:
            temp = invoice_data
            valid_path = True
            
            for part in path:
                if isinstance(temp, dict) and part in temp:
                    temp = temp[part]
                else:
                    valid_path = False
                    break
            
            if valid_path and isinstance(temp, list) and len(temp) > 0:
                line_items_data = temp
                logger.debug(f"Found {len(line_items_data)} line items using path {path}")
                break
        
        # Try to parse line items with different field naming conventions
        for item in line_items_data:
            if not isinstance(item, dict):
                logger.warning(f"Skipping non-dictionary line item: {item}")
                continue
                
            # Log the structure of this line item
            logger.debug(f"Processing line item with keys: {list(item.keys())}")
            
            # Extract line item fields with flexible field names
            description = None
            for key in ["description", "desc", "item", "product", "service", "name", "title"]:
                if key in item and item[key]:
                    description = str(item[key])
                    break
            
            quantity = None
            for key in ["quantity", "qty", "units", "count"]:
                if key in item and item[key] is not None:
                    quantity_val = item[key]
                    if isinstance(quantity_val, (int, float)):
                        quantity = quantity_val
                    elif isinstance(quantity_val, str):
                        try:
                            quantity = float(quantity_val)
                        except:
                            pass
                    elif isinstance(quantity_val, dict) and "value" in quantity_val:
                        quantity = quantity_val["value"]
                    break
            
            # Default to 1 if no quantity found
            if quantity is None:
                quantity = 1.0
            
            unit_price = None
            for key in ["unit_price", "unitPrice", "price", "rate", "unit_cost"]:
                if key in item:
                    price_val = item[key]
                    if isinstance(price_val, (int, float)):
                        unit_price = price_val
                    elif isinstance(price_val, str):
                        try:
                            # Remove currency symbols and convert to float
                            price_str = ''.join(c for c in price_val if c.isdigit() or c == '.')
                            unit_price = float(price_str) if price_str else 0
                        except:
                            pass
                    elif isinstance(price_val, dict) and "amount" in price_val:
                        unit_price = price_val["amount"]
                    elif isinstance(price_val, dict) and "value" in price_val:
                        unit_price = price_val["value"]
                    break
            
            if unit_price is None:
                unit_price = 0.0
            
            amount = None
            for key in ["amount", "total", "line_total", "subtotal", "line_amount"]:
                if key in item:
                    amount_val = item[key]
                    if isinstance(amount_val, (int, float)):
                        amount = amount_val
                    elif isinstance(amount_val, str):
                        try:
                            # Remove currency symbols and convert to float
                            amount_str = ''.join(c for c in amount_val if c.isdigit() or c == '.')
                            amount = float(amount_str) if amount_str else 0
                        except:
                            pass
                    elif isinstance(amount_val, dict) and "amount" in amount_val:
                        amount = amount_val["amount"]
                    elif isinstance(amount_val, dict) and "value" in amount_val:
                        amount = amount_val["value"]
                    break
            
            # If amount is not found but we have quantity and unit_price, calculate it
            if amount is None and quantity is not None and unit_price is not None:
                amount = quantity * unit_price
            elif amount is None:
                amount = 0.0
            
            tax = None
            for key in ["tax", "vat", "gst", "sales_tax", "tax_amount"]:
                if key in item:
                    tax_val = item[key]
                    if isinstance(tax_val, (int, float)):
                        tax = tax_val
                    elif isinstance(tax_val, str):
                        try:
                            # Remove currency symbols and convert to float
                            tax_str = ''.join(c for c in tax_val if c.isdigit() or c == '.')
                            tax = float(tax_str) if tax_str else 0
                        except:
                            pass
                    elif isinstance(tax_val, dict) and "amount" in tax_val:
                        tax = tax_val["amount"]
                    elif isinstance(tax_val, dict) and "value" in tax_val:
                        tax = tax_val["value"]
                    break
            
            if tax is None:
                tax = 0.0
            
            # Look for project number and activity code in the description
            project_number = None
            project_name = None
            activity_code = None
            
            # Extract project data from specific keys if available
            for key in ["project", "project_number", "job", "job_number", "project_id"]:
                if key in item and item[key]:
                    project_number = str(item[key])
                    break
            
            for key in ["project_name", "job_name", "project_description"]:
                if key in item and item[key]:
                    project_name = str(item[key])
                    break
            
            for key in ["activity_code", "activity", "task_code", "task"]:
                if key in item and item[key]:
                    activity_code = str(item[key])
                    break
            
            # Attempt to extract project number and activity code using regex patterns if still not found
            if description and not project_number:
                project_number_pattern = r'(?:Project|PN|Job)\s*(?:Number|#|No\.?|ID)?\s*[:=\s]\s*([A-Z0-9-]+)'
                project_number_match = re.search(project_number_pattern, description)
                if project_number_match:
                    project_number = project_number_match.group(1)
            
            if description and not activity_code:
                activity_code_pattern = r'(?:Activity|Task)\s*(?:Code|#|No\.?)?\s*[:=\s]\s*([A-Z0-9-]+)'
                activity_code_match = re.search(activity_code_pattern, description)
                if activity_code_match:
                    activity_code = activity_code_match.group(1)
            
            # Create line item with all extracted data
            line_item = {
                "description": description if description else "",
                "quantity": float(quantity),
                "unit_price": float(unit_price),
                "amount": float(amount),
                "tax": float(tax),
                "project_number": project_number,
                "project_name": project_name,
                "activity_code": activity_code
            }
            
            line_items.append(line_item)
            logger.debug(f"Processed line item: description='{description}', amount={amount}")
        
        # If no line items were found, but we have table data, try to extract from tables
        if not line_items and "tables" in invoice_data and isinstance(invoice_data["tables"], list):
            logger.debug("No line items found, attempting to extract from tables")
            for table in invoice_data["tables"]:
                if isinstance(table, dict) and "rows" in table and isinstance(table["rows"], list):
                    # Skip the header row, use the rest as line items
                    for row in table["rows"][1:] if len(table["rows"]) > 1 else table["rows"]:
                        if isinstance(row, dict) and "cells" in row and isinstance(row["cells"], list):
                            cells = row["cells"]
                            if len(cells) >= 2:  # At minimum we need description and amount
                                line_item = {
                                    "description": cells[0] if len(cells) > 0 else "",
                                    "quantity": float(cells[1]) if len(cells) > 1 and cells[1] and cells[1].replace('.','',1).isdigit() else 1.0,
                                    "unit_price": float(cells[2]) if len(cells) > 2 and cells[2] and cells[2].replace('.','',1).isdigit() else 0.0,
                                    "amount": float(cells[3]) if len(cells) > 3 and cells[3] and cells[3].replace('.','',1).isdigit() else 0.0,
                                    "tax": 0.0,
                                    "project_number": None,
                                    "project_name": None,
                                    "activity_code": None
                                }
                                line_items.append(line_item)
        
        # Assemble the transformed data
        transformed_data = {
            "vendor_name": vendor_name if vendor_name else "Unknown Vendor",
            "invoice_number": invoice_number if invoice_number else "",
            "invoice_date": invoice_date if invoice_date else "",
            "due_date": due_date if due_date else "",
            "total_amount": float(total_amount) if total_amount else 0.0,
            "file_name": file_name,
            "line_items": line_items
        }
        
        # Log a summary of what we extracted
        logger.debug(f"Transformation summary for {file_name}:")
        logger.debug(f"  - Vendor: {transformed_data['vendor_name']}")
        logger.debug(f"  - Invoice #: {transformed_data['invoice_number']}")
        logger.debug(f"  - Date: {transformed_data['invoice_date']}")
        logger.debug(f"  - Total: {transformed_data['total_amount']}")
        logger.debug(f"  - Line items: {len(transformed_data['line_items'])}")
        
        return transformed_data
        
    except Exception as e:
        logger.exception(f"Error transforming LlamaCloud data: {str(e)}")
        # Raise the exception instead of silently returning empty data
        raise ValueError(f"Failed to transform LlamaCloud data: {str(e)}")


# Only using LlamaCloud for document parsing now
# This code has been replaced with LlamaCloud API integration

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
