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
        
        # If successful, log it
        if result.get('success'):
            logger.info("Successfully parsed invoice with LlamaCloud")
        else:
            # Log error
            error_msg = result.get('error', 'Unknown error with LlamaCloud')
            logger.error(f"LlamaCloud parsing failed: {error_msg}")
        
        return result
            
    except Exception as e:
        # Catch any exception that might occur during parsing
        error_msg = str(e)
        logger.exception(f"Unexpected error in invoice parsing: {error_msg}")
        
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
    
    # Get vendor name for mapping lookup
    vendor_name = safe(invoice_data.get('vendor', {}).get('name'))
    
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
        else:
            logger.debug(f"Extraction data is not a dictionary: {str(extraction_data)[:200]}")
        
        # Get the invoice extraction results - the format is different in our API response
        # In the parsing API, the invoice data may be at the root level
        invoice_data = extraction_data
        
        # Look for invoice properties in expected locations
        vendor_info = None
        vendor_name = "Unknown Vendor"
        
        # Try to extract vendor info
        if "vendor" in invoice_data:
            vendor_info = invoice_data.get("vendor", {})
            if isinstance(vendor_info, dict):
                vendor_name = vendor_info.get("name", "Unknown Vendor")
            elif isinstance(vendor_info, str):
                vendor_name = vendor_info
        
        # Extract invoice metadata - try different possible field names
        invoice_number = invoice_data.get("invoiceNumber", invoice_data.get("invoice_number", ""))
        invoice_date = invoice_data.get("invoiceDate", invoice_data.get("date", ""))
        due_date = invoice_data.get("dueDate", invoice_data.get("due_date", ""))
        
        # Extract total amount - handle different formats
        total_amount = 0
        if "totalAmount" in invoice_data:
            total_info = invoice_data.get("totalAmount", {})
            if isinstance(total_info, dict) and "amount" in total_info:
                total_amount = total_info.get("amount", 0)
            else:
                total_amount = total_info
        elif "total" in invoice_data:
            total_amount = invoice_data.get("total", 0)
        
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
