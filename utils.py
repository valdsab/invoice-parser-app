import os
import json
import logging
import requests
import re
import time
from app import app

logger = logging.getLogger(__name__)

# Timeout settings
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
        
        # Create transformed invoice data structure
        transformed_invoice_data = {
            'vendor_name': vendor_name,
            'vendor': {'name': vendor_name} if vendor_name else {},
            'invoice_number': invoice_number,
            'invoice_date': invoice_date,
            'due_date': due_date,
            'total_amount': total_amount,
            'line_items': [],
            'file_name': file_name
        }
        
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
            
            if valid_path and isinstance(temp, list):
                line_items_data = temp
                logger.debug(f"Found {len(line_items_data)} line items using path {path}")
                break
        
        # Process line items
        for item in line_items_data:
            if not isinstance(item, dict):
                continue
                
            line_item = {
                'description': None,
                'quantity': None,
                'unit_price': None,
                'amount': None,
                'tax': None
            }
            
            # Try to extract description
            for desc_key in ['description', 'desc', 'item', 'name', 'product', 'service']:
                if desc_key in item and item[desc_key]:
                    line_item['description'] = item[desc_key]
                    break
            
            # Try to extract quantity
            for qty_key in ['quantity', 'qty', 'count', 'units']:
                if qty_key in item and item[qty_key] is not None:
                    try:
                        line_item['quantity'] = float(item[qty_key])
                    except (ValueError, TypeError):
                        pass
                    break
            
            # Try to extract unit price
            for price_key in ['unit_price', 'price', 'rate', 'unit_cost']:
                if price_key in item and item[price_key] is not None:
                    try:
                        line_item['unit_price'] = float(item[price_key])
                    except (ValueError, TypeError):
                        pass
                    break
            
            # Try to extract amount
            for amount_key in ['amount', 'total', 'line_total', 'extended_price']:
                if amount_key in item and item[amount_key] is not None:
                    try:
                        line_item['amount'] = float(item[amount_key])
                    except (ValueError, TypeError):
                        pass
                    break
            
            # Try to extract tax
            for tax_key in ['tax', 'tax_amount', 'vat', 'gst']:
                if tax_key in item and item[tax_key] is not None:
                    try:
                        line_item['tax'] = float(item[tax_key])
                    except (ValueError, TypeError):
                        pass
                    break
            
            transformed_invoice_data['line_items'].append(line_item)
        
        logger.debug(f"Transformed data: {json.dumps(transformed_invoice_data, indent=2)}")
        return transformed_invoice_data
        
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
            return {'success': False, 'error': "Missing API key"}

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

        logger.debug(f"Uploading invoice file: {file_path}")
        with open(file_path, "rb") as f:
            file_data = {'file': (file_name, f.read(), mime_type)}
            response = requests.post(upload_url, headers=headers, files=file_data, timeout=API_REQUEST_TIMEOUT)

        response.raise_for_status()
        job_data = response.json()
        job_id = job_data.get("id")
        if not job_id:
            raise Exception(f"No job ID returned: {job_data}")

        logger.debug(f"LlamaCloud job created with ID: {job_id}")
        status_url = f"{base_url}/api/parsing/job/{job_id}"
        start_time = time.time()
        extraction_data = None
        
        while time.time() - start_time < MAX_POLLING_TIMEOUT:
            status_response = requests.get(status_url, headers=headers, timeout=API_REQUEST_TIMEOUT)
            status_response.raise_for_status()
            status_data = status_response.json()
            job_status = status_data.get("status")
            logger.debug(f"LlamaCloud job status: {job_status}")
            
            if job_status in ["COMPLETE", "SUCCESS", "success"]:
                extraction_data = status_data
                logger.debug("LlamaCloud processing completed successfully")
                break
            if job_status in ["ERROR", "FAILED", "error", "failed"]:
                logger.error(f"LlamaCloud processing failed: {status_data}")
                return {'success': False, 'error': f"LlamaCloud error: {status_data.get('error', 'Unknown error')}"}
            time.sleep(2)

        if time.time() - start_time >= MAX_POLLING_TIMEOUT:
            logger.error("Timeout waiting for LlamaCloud processing")
            return {'success': False, 'error': "Timeout while waiting for LlamaCloud processing"}

        if not extraction_data:
            logger.error("No extraction data received from LlamaCloud")
            return {'success': False, 'error': "No extraction data received from LlamaCloud"}
            
        logger.debug(f"LlamaCloud extraction data: {str(extraction_data)[:200]}...")
        
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
