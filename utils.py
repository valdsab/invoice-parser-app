import os
import json
import logging
import requests
import re
import time
from app import app

logger = logging.getLogger(__name__)

API_REQUEST_TIMEOUT = 30
MAX_POLLING_TIMEOUT = 25

def clean_id(id_value):
    """
    Clean and standardize ID values, particularly UUIDs.
    
    Args:
        id_value: ID to clean (string or bytes)
        
    Returns:
        str: Cleaned ID value
    """
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
    """
    Check if a file is allowed based on extension and MIME type
    
    Args:
        filename: Name of the file to check
        mime_type: Optional MIME type to validate
        
    Returns:
        bool: True if file is allowed, False otherwise
    """
    if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']):
        return False
    if mime_type:
        allowed_mime_types = {
            'application/pdf': ['pdf'],
            'image/jpeg': ['jpg', 'jpeg'],
            'image/png': ['png']
        }
        extension = filename.rsplit('.', 1)[1].lower()
        if mime_type not in allowed_mime_types or extension not in allowed_mime_types[mime_type]:
            return False
    return True

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

    default = {
        'field_mappings': {
            'invoice_number': ['invoice_number', 'invoice #', 'bill #'],
            'invoice_date': ['invoice_date', 'date'],
            'due_date': ['due_date'],
            'total_amount': ['total_amount', 'total'],
            'line_items': {
                'description': ['description', 'item'],
                'project_number': ['project_number'],
                'project_name': ['project_name'],
                'activity_code': ['activity_code'],
                'quantity': ['quantity'],
                'unit_price': ['unit_price'],
                'amount': ['amount'],
                'tax': ['tax']
            }
        },
        'regex_patterns': {
            'project_number': r'(?:PN|Project)\s*[:=]?\s*([A-Z0-9\-]+)',
            'activity_code': r'(?:Activity|Task)\s*(?:Code)?\s*[:=]?\s*([A-Z0-9\-]+)'
        }
    }

    try:
        if session is None:
            session = db.session

        vm = session.query(VendorMapping).filter(
            VendorMapping.vendor_name == vendor_name,
            VendorMapping.is_active == True
        ).first()

        if vm and vm.field_mappings:
            return {
                'field_mappings': json.loads(vm.field_mappings),
                'regex_patterns': json.loads(vm.regex_patterns) if vm.regex_patterns else {}
            }

        return default
    except Exception as e:
        logger.warning(f"Vendor mapping fallback due to error: {str(e)}")
        return default

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
        logger.debug(f"Transforming LlamaCloud data for: {file_name}")
        if isinstance(extraction_data, dict):
            for potential_key in ['data', 'document', 'results', 'content', 'extraction']:
                if potential_key in extraction_data and isinstance(extraction_data[potential_key], dict):
                    extraction_data = extraction_data[potential_key]
                    break

        invoice_data = extraction_data
        transformed = {
            'vendor_name': None,
            'invoice_number': None,
            'invoice_date': None,
            'due_date': None,
            'total_amount': 0.0,
            'line_items': [],
            'file_name': file_name
        }

        def find_field(paths):
            for path in paths:
                temp = invoice_data
                for part in path:
                    if isinstance(temp, dict) and part in temp:
                        temp = temp[part]
                    else:
                        temp = None
                        break
                if temp:
                    return temp
            return None

        transformed['vendor_name'] = find_field([
            ('vendor', 'name'), ('vendor_name',), ('supplier_name',), ('company_name',)
        ]) or "Unknown Vendor"

        transformed['invoice_number'] = str(find_field([
            ('invoice_number',), ('invoiceNumber',), ('id',), ('number',)
        ]) or "")

        transformed['invoice_date'] = str(find_field([
            ('invoice_date',), ('date',), ('issue_date',)
        ]) or "")

        transformed['due_date'] = str(find_field([
            ('due_date',), ('payment_due',)
        ]) or "")

        amount = find_field([
            ('total_amount',), ('total',), ('grand_total',)
        ])
        if isinstance(amount, dict) and 'amount' in amount:
            amount = amount['amount']
        try:
            transformed['total_amount'] = float(str(amount).replace('$', '').replace(',', '')) if amount else 0.0
        except:
            transformed['total_amount'] = 0.0

        # Extract line items
        for line_path in [('line_items',), ('items',), ('details',)]:
            items = find_field([line_path])
            if items and isinstance(items, list):
                for item in items:
                    transformed['line_items'].append(item)
                break

        logger.debug(f"Transformed LlamaCloud data keys: {list(transformed.keys())}")
        return transformed

    except Exception as e:
        logger.exception("Error in transform_llama_cloud_to_invoice_format")
        return {
            'vendor_name': None,
            'invoice_number': None,
            'invoice_date': None,
            'due_date': None,
            'total_amount': 0.0,
            'line_items': [],
            'file_name': file_name,
            'error': str(e)
        }

def normalize_invoice(invoice_data):
    """
    Normalize invoice data from LlamaCloud response with vendor-specific mappings
    
    Args:
        invoice_data: Raw response data from LlamaCloud
        
    Returns:
        dict: Normalized invoice data with consistent fields
    """
    def safe(v): return v if v is not None else None

    vendor_name = safe(invoice_data.get('vendor_name'))
    mapping = get_vendor_mapping(vendor_name)
    field_mappings = mapping['field_mappings']
    regex_patterns = mapping['regex_patterns']

    invoice = {
        'vendor_name': vendor_name,
        'invoice_number': None,
        'invoice_date': None,
        'due_date': None,
        'total_amount': 0.0,
        'line_items': [],
        'raw_response': invoice_data
    }

    for target, sources in field_mappings.items():
        if target == 'line_items':
            continue
        for src in sources:
            val = invoice_data.get(src)
            if val:
                invoice[target] = val
                break

    try:
        invoice['total_amount'] = float(invoice.get('total_amount', 0) or 0)
    except:
        invoice['total_amount'] = 0.0

    item_map = field_mappings.get('line_items', {})
    for raw in invoice_data.get('line_items', []):
        item = {
            'description': '', 'project_number': '', 'project_name': '',
            'activity_code': '', 'quantity': 1.0, 'unit_price': 0.0,
            'amount': 0.0, 'tax': 0.0
        }
        for tgt, src_list in item_map.items():
            for src in src_list:
                if src in raw:
                    item[tgt] = raw[src]
                    break

        desc = item.get('description') or ''
        for field, pattern in regex_patterns.items():
            if not item.get(field) and desc:
                match = extract_from_desc(desc, pattern)
                if match:
                    item[field] = match

        for num_field in ['quantity', 'unit_price', 'amount', 'tax']:
            try:
                item[num_field] = float(item[num_field] or 0)
            except:
                item[num_field] = 0.0

        invoice['line_items'].append(item)

    return invoice

def parse_invoice(file_path):
    """
    Parse an invoice file using the appropriate parser
    
    Args:
        file_path: Path to the invoice file
        
    Returns:
        dict: Parsing result with success status and data or error
    """
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
    """
    Parse an invoice file using LlamaCloud API
    
    Args:
        file_path: Path to the invoice file
        
    Returns:
        dict: Parsing result with success status and data or error
    """
    try:
        if not os.path.exists(file_path):
            return {'success': False, 'error': f"File not found: {file_path}"}
        if os.path.getsize(file_path) == 0:
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

            if job_status.lower() in ["complete", "success"]:
                extraction_data = status_data
                logger.debug("LlamaCloud processing completed successfully")
                break
            if job_status.lower() in ["error", "failed"]:
                logger.error(f"LlamaCloud processing failed: {status_data}")
                return {'success': False, 'error': f"LlamaCloud error: {status_data.get('error', 'Unknown error')}"}
            time.sleep(2)

        if not extraction_data:
            logger.error("No extraction data received from LlamaCloud")
            return {'success': False, 'error': "No extraction data received from LlamaCloud"}

        logger.debug(f"LlamaCloud extraction data: {str(extraction_data)[:200]}...")

        try:
            transformed_data = transform_llama_cloud_to_invoice_format(extraction_data, file_name)
            if not transformed_data:
                return {'success': False, 'error': "Transformation failed", 'raw_extraction_data': extraction_data}
            invoice_data = normalize_invoice(transformed_data)
            return {
                'success': True,
                'data': invoice_data,
                'raw_extraction_data': extraction_data
            }
        except Exception as e:
            logger.exception("Transformation/Normalization failed")
            return {
                'success': False,
                'error': f"Processing error: {str(e)}",
                'raw_extraction_data': extraction_data
            }

    except Exception as e:
        logger.exception("LlamaCloud parsing error")
        return {'success': False, 'error': str(e)}
