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

def parse_invoice_with_eyelevel(file_path):
    """
    Parse invoice using the GroundX SDK (Eyelevel.ai)
    
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
        # We'll need to patch the underlying HTTP client to handle header values properly
        
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
        
        # Create or use existing bucket
        try:
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
        
        # Upload file
        logger.debug(f"Uploading document to GroundX: {file_path}")
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
        
        # Wait for processing
        process_id = clean_id(upload_response.ingest.process_id)
            
        logger.debug(f"Document uploaded. Process ID: {process_id}")
        
        logger.debug("Waiting for document processing to complete...")
        max_wait_time = 60  # maximum wait time in seconds
        start_time = time.time()
        
        while True:
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
            
            # Check if we've waited too long
            if time.time() - start_time > max_wait_time:
                logger.error(f"Document processing timed out after {max_wait_time} seconds")
                return {
                    'success': False,
                    'error': f"Processing timeout after {max_wait_time} seconds"
                }
                
            time.sleep(3)
        
        # Fetch parsed document
        # Ensure bucket_id is properly formatted before lookup
        bucket_id = clean_id(bucket_id)
            
        document_response = client.documents.lookup(id=bucket_id)
        if not document_response.documents:
            raise Exception("No documents found in bucket after processing")
        
        # Get the most recently uploaded document (should be the one we just processed)
        document = document_response.documents[0]
        xray_url = document.xray_url
        
        logger.debug(f"Retrieving X-Ray data from: {xray_url}")
        
        # Get full X-Ray output
        with urllib.request.urlopen(xray_url) as url:
            xray_data = json.loads(url.read().decode())
        
        logger.debug("X-Ray data retrieved successfully")
        
        # Transform X-Ray data into our expected format
        transformed_data = transform_xray_to_invoice_format(xray_data, file_name)
        
        # Use the normalize_invoice function to standardize data across different vendors
        invoice_data = normalize_invoice(transformed_data)
        
        logger.debug(f"Normalized invoice data: {json.dumps(invoice_data, indent=2)}")
        
        return {
            'success': True,
            'data': invoice_data
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

def normalize_invoice(eyelevel_data):
    """
    Normalize invoice data from Eyelevel.ai response
    
    Args:
        eyelevel_data: Raw response data from Eyelevel.ai
        
    Returns:
        dict: Normalized invoice data with consistent fields
    """
    # Safe access helper function
    def safe(v):
        return v if v is not None else None
    
    # Create base invoice object with normalized fields
    invoice = {
        'vendor_name': safe(eyelevel_data.get('vendor', {}).get('name')),
        'invoice_number': safe(eyelevel_data.get('invoice_number')),
        'invoice_date': safe(eyelevel_data.get('date')),
        'due_date': safe(eyelevel_data.get('due_date')),
        'total_amount': float(eyelevel_data.get('total_amount', 0) or 0),
        'line_items': [],
        'raw_response': eyelevel_data  # Keep the raw response for debugging
    }
    
    # Process line items with consistent field structure
    if eyelevel_data.get('line_items') and isinstance(eyelevel_data['line_items'], list):
        for item in eyelevel_data['line_items']:
            description = item.get('description') or ''
            
            line_item = {
                'description': description,
                'project_number': item.get('project_number') or extract_from_desc(description, r'PN:?\s*(\d+)'),
                'project_name': item.get('project_name') or '',
                'activity_code': item.get('activity_code') or '',
                'quantity': float(item.get('quantity', 1) or 1),
                'unit_price': float(item.get('unit_price', 0) or 0),
                'amount': float(item.get('amount', 0) or 0),
                'tax': float(item.get('tax', 0) or 0)
            }
            
            invoice['line_items'].append(line_item)
    
    logger.debug(f"Normalized invoice data: {json.dumps(invoice, indent=2)}")
    return invoice

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
