
import os
import json
import logging
import requests
import re
import time
from app import app, db

logger = logging.getLogger(__name__)

API_REQUEST_TIMEOUT = 30
MAX_POLLING_TIMEOUT = 25

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
            
            # LlamaCloud often puts the actual data in a nested structure
            for potential_key in ['data', 'document', 'invoice', 'results', 'content', 'extraction']:
                if potential_key in extraction_data and extraction_data[potential_key]:
                    logger.debug(f"Found potential data in '{potential_key}' field")
                    if isinstance(extraction_data[potential_key], dict):
                        # Store original data for reference
                        original_data = extraction_data
                        extraction_data = extraction_data[potential_key]
                        
                        # Copy important fields if they exist at top level but not in selected data
                        for key in ['id', 'job_id', 'status', 'document_id']:
                            if key in original_data and key not in extraction_data:
                                extraction_data[key] = original_data[key]
                                
                        logger.debug(f"Using '{potential_key}' as root. New keys: {list(extraction_data.keys())}")
                        break
        
        # Get invoice properties from various possible locations
        # Try vendor name from different fields
        vendor_name = None
        for key in ['vendor_name', 'vendor', 'supplier', 'supplier_name', 'from_company', 'company', 'company_name']:
            if key in extraction_data:
                value = extraction_data[key]
                if isinstance(value, dict) and 'name' in value:
                    vendor_name = value['name']
                elif isinstance(value, str):
                    vendor_name = value
                if vendor_name:
                    logger.debug(f"Found vendor name: {vendor_name}")
                    break
        
        # Try invoice number from different fields
        invoice_number = None
        for key in ['invoice_number', 'id', 'invoice_id', 'number', 'document_number']:
            if key in extraction_data:
                invoice_number = str(extraction_data[key])
                logger.debug(f"Found invoice number: {invoice_number}")
                break
        
        # Try invoice date from different fields
        invoice_date = None
        for key in ['invoice_date', 'date', 'issue_date']:
            if key in extraction_data:
                invoice_date = extraction_data[key]
                logger.debug(f"Found invoice date: {invoice_date}")
                break
        
        # Try due date from different fields
        due_date = None
        for key in ['due_date', 'payment_due', 'payment_due_date']:
            if key in extraction_data:
                due_date = extraction_data[key]
                logger.debug(f"Found due date: {due_date}")
                break
        
        # Try total amount from different fields
        total_amount = 0
        for key in ['total_amount', 'total', 'amount', 'grand_total']:
            if key in extraction_data:
                value = extraction_data[key]
                if isinstance(value, (int, float)):
                    total_amount = value
                elif isinstance(value, str):
                    try:
                        # Remove any non-digit characters except decimal point
                        amount_str = ''.join(c for c in value if c.isdigit() or c == '.')
                        total_amount = float(amount_str) if amount_str else 0
                    except (ValueError, TypeError):
                        pass
                logger.debug(f"Found total amount: {total_amount}")
                break
        
        # Find line items
        line_items = []
        for key in ['line_items', 'items', 'lines', 'invoice_items']:
            if key in extraction_data and isinstance(extraction_data[key], list):
                line_items = extraction_data[key]
                logger.debug(f"Found {len(line_items)} line items")
                break
        
        # Create transformed data structure
        transformed_data = {
            'vendor_name': vendor_name,
            'vendor': {'name': vendor_name} if vendor_name else {},
            'invoice_number': invoice_number,
            'invoice_date': invoice_date,
            'due_date': due_date,
            'total_amount': total_amount,
            'line_items': line_items,
            'file_name': file_name
        }
        
        logger.debug(f"Transformed data: {json.dumps(transformed_data, indent=2)}")
        return transformed_data
        
    except Exception as e:
        logger.exception(f"Error transforming LlamaCloud data: {str(e)}")
        # Return a minimal structure so we can continue processing
        return {
            'vendor_name': None,
            'invoice_number': None,
            'invoice_date': None, 
            'due_date': None,
            'total_amount': 0,
            'line_items': [],
            'file_name': file_name,
            'error': str(e)
        }

def clean_id(id_value):
    if isinstance(id_value, bytes):
        id_value = id_value.decode('utf-8', errors='ignore')
    cleaned_id = str(id_value).strip()
    cleaned_id = re.sub(r'\s+', '', cleaned_id)
    if re.match(r'^[0-9a-f-]{36}$', cleaned_id, re.IGNORECASE):
        uuid_parts = cleaned_id.replace('-', '')
        if len(uuid_parts) == 32:
            cleaned_id = f"{uuid_parts[0:8]}-{uuid_parts[8:12]}-{uuid_parts[12:16]}-{uuid_parts[16:20]}-{uuid_parts[20:32]}"
    return cleaned_id

def allowed_file(filename, mime_type=None):
    if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']):
        return False
    if mime_type:
        allowed_mime_types = {
            'application/pdf': ['pdf'],
            'image/jpeg': ['jpg', 'jpeg'],
            'image/png': ['png']
        }
        if mime_type not in allowed_mime_types:
            return False
        extension = filename.rsplit('.', 1)[1].lower()
        if extension not in allowed_mime_types.get(mime_type, []):
            return False
    return True

def parse_invoice(file_path):
    parser_used = "LlamaCloud"
    try:
        api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
        if not api_key:
            return {
                'success': False,
                'error': "LlamaCloud API key not configured. Please set the LLAMA_CLOUD_API_ENTOS environment variable.",
                'parser_used': parser_used
            }
        result = parse_invoice_with_llama_cloud(file_path)
        result['parser_used'] = parser_used
        return result
    except Exception as e:
        logger.exception("Unexpected error in invoice parsing")
        return {
            'success': False,
            'error': f"Invoice parsing failed: {str(e)}",
            'parser_used': parser_used
        }

def parse_invoice_with_llama_cloud(file_path):
    try:
        if not os.path.exists(file_path):
            return {'success': False, 'error': f"File not found: {file_path}"}
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return {'success': False, 'error': "Empty file"}

        api_key = os.environ.get('LLAMA_CLOUD_API_ENTOS')
        if not api_key:
            return {'success': False, 'error': "Missing LlamaCloud API key"}

        file_name = os.path.basename(file_path)
        file_extension = os.path.splitext(file_name)[1].lower()
        base_url = "https://api.cloud.llamaindex.ai"
        upload_url = f"{base_url}/api/parsing/upload"

        mime_type = 'application/pdf'
        if file_extension in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif file_extension == '.png':
            mime_type = 'image/png'

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }

        logger.debug(f"Uploading to LlamaCloud: {file_name}")
        with open(file_path, "rb") as f:
            files = {'file': (file_name, f.read(), mime_type)}
            response = requests.post(upload_url, headers=headers, files=files, timeout=API_REQUEST_TIMEOUT)

        response.raise_for_status()
        job_data = response.json()
        job_id = job_data.get("id")

        if not job_id:
            raise ValueError(f"No job ID returned: {job_data}")

        logger.debug(f"LlamaCloud job ID: {job_id}")
        status_url = f"{base_url}/api/parsing/job/{job_id}"
        start_time = time.time()
        extraction_data = None

        while time.time() - start_time < MAX_POLLING_TIMEOUT:
            status_response = requests.get(status_url, headers=headers, timeout=API_REQUEST_TIMEOUT)
            status_response.raise_for_status()
            status_data = status_response.json()
            job_status = status_data.get("status", "").upper()

            logger.debug(f"LlamaCloud job status: {job_status}")
            if job_status in ["COMPLETE", "SUCCESS"]:
                extraction_data = status_data
                break
            if job_status in ["FAILED", "ERROR"]:
                return {'success': False, 'error': f"LlamaCloud error: {status_data.get('error', 'Unknown')}"}
            time.sleep(2)

        if not extraction_data:
            return {'success': False, 'error': "Timeout waiting for LlamaCloud"}

        logger.debug(f"Extraction data received for {file_name}")

        transformed_data = transform_llama_cloud_to_invoice_format(extraction_data, file_name)
        if not transformed_data:
            return {'success': False, 'error': "Transformation failed", 'raw_extraction_data': extraction_data}

        invoice_data = normalize_invoice(transformed_data)
        if not invoice_data:
            return {'success': False, 'error': "Normalization failed", 'transformed_data': transformed_data}

        logger.debug(f"Parsed invoice fields: vendor={invoice_data.get('vendor_name')}, total={invoice_data.get('total_amount')}")

        return {
            'success': True,
            'data': invoice_data,
            'raw_extraction_data': extraction_data
        }

    except Exception as e:
        logger.exception("Fatal error in LlamaCloud parsing")
        return {'success': False, 'error': str(e)}
