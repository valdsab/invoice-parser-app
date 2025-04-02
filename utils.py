import os
import json
import logging
import requests
import re
from app import app

logger = logging.getLogger(__name__)

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
    from groundx import GroundX, Document
    import urllib.request
    import time
    import os
    
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
        client = GroundX(api_key=api_key)
        
        # Create or use existing bucket
        try:
            bucket_response = client.buckets.create(name="invoice_docs")
            bucket_id = bucket_response.bucket.bucket_id
            logger.debug(f"Created new bucket: {bucket_id}")
        except Exception as bucket_error:
            # Bucket might already exist, try to get existing buckets
            logger.debug(f"Error creating bucket, will try to use existing: {str(bucket_error)}")
            buckets_response = client.buckets.list()
            if not buckets_response.buckets:
                raise Exception("Failed to create or find any buckets")
            bucket_id = buckets_response.buckets[0].bucket_id
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
        process_id = upload_response.ingest.process_id
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
        "line_items": []
    }
    
    try:
        # Extract data from document pages and chunks
        if "documentPages" not in xray_data:
            logger.warning("No document pages found in X-Ray data")
            return transformed_data
        
        # Extract fields from chunks
        for page in xray_data["documentPages"]:
            if "chunks" not in page:
                continue
                
            for chunk in page["chunks"]:
                chunk_type = chunk.get("chunkType", "").lower()
                text = chunk.get("content", {}).get("text", "")
                
                # Extract vendor information
                if chunk_type == "vendor" or "vendor" in chunk_type:
                    transformed_data["vendor"]["name"] = text
                
                # Extract invoice number
                elif chunk_type == "invoice number" or "invoice number" in chunk_type:
                    transformed_data["invoice_number"] = text
                
                # Extract invoice date
                elif chunk_type == "invoice date" or chunk_type == "date":
                    transformed_data["date"] = text
                
                # Extract due date
                elif chunk_type == "due date":
                    transformed_data["due_date"] = text
                
                # Extract total amount
                elif "total" in chunk_type and ("amount" in chunk_type or "cost" in chunk_type):
                    # Remove any non-numeric characters except decimal point
                    amount = ''.join(c for c in text if c.isdigit() or c == '.')
                    transformed_data["total_amount"] = amount
                
                # Extract line items
                elif chunk_type == "line item" or "item" in chunk_type:
                    # Basic line item with description only
                    line_item = {
                        "description": text,
                        "quantity": "1",
                        "unit_price": "0",
                        "amount": "0",
                        "tax": "0"
                    }
                    
                    # Try to extract more detailed line item information
                    if "lineItems" in chunk.get("content", {}):
                        for line_details in chunk["content"]["lineItems"]:
                            if "quantity" in line_details:
                                line_item["quantity"] = str(line_details["quantity"])
                            if "unitPrice" in line_details:
                                line_item["unit_price"] = str(line_details["unitPrice"])
                            if "amount" in line_details:
                                line_item["amount"] = str(line_details["amount"])
                            if "tax" in line_details:
                                line_item["tax"] = str(line_details["tax"])
                    
                    transformed_data["line_items"].append(line_item)
        
        # If we couldn't extract any line items but have tables, try to extract from tables
        if not transformed_data["line_items"] and "tables" in xray_data:
            for table in xray_data["tables"]:
                # Skip header row
                for row in table.get("rows", [])[1:]:
                    # Basic extraction assuming common table structure
                    if len(row) >= 4:  # At least description, quantity, price, amount
                        line_item = {
                            "description": row[0] if row[0] else "Unlabeled item",
                            "quantity": row[1] if len(row) > 1 else "1",
                            "unit_price": row[2] if len(row) > 2 else "0",
                            "amount": row[3] if len(row) > 3 else "0",
                            "tax": row[4] if len(row) > 4 else "0",
                        }
                        transformed_data["line_items"].append(line_item)
        
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
