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
    Simulated invoice parsing function (replaces actual Eyelevel.ai API call)
    
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
        
        logger.debug("Using simulated OCR response for testing")
        
        # Generate a simulated response based on the file
        filename = os.path.basename(file_path)
        logger.debug(f"Generating simulated OCR response for {filename}")
        
        # Create a simulated response
        response_data = {
            "vendor": {
                "name": "ACME Corporation",
                "address": "123 Business St, Suite 100, San Francisco, CA 94107",
                "phone": "555-123-4567",
                "email": "billing@acmecorp.com"
            },
            "invoice_number": f"INV-{filename.split('.')[0][-4:]}",
            "date": "2025-03-15",
            "due_date": "2025-04-15",
            "total_amount": "1250.00",
            "line_items": [
                {
                    "description": "Web Development Services PN: 10002",
                    "quantity": "25",
                    "unit_price": "50.00",
                    "amount": "1250.00",
                    "tax": "0.00",
                    "project_name": "Site C"
                }
            ]
        }
        
        logger.debug(f"Generated simulated OCR response: {json.dumps(response_data, indent=2)}")
        
        # Use the normalize_invoice function to standardize data across different vendors
        invoice_data = normalize_invoice(response_data)
        
        logger.debug(f"Normalized invoice data: {json.dumps(invoice_data, indent=2)}")
        return {
            'success': True,
            'data': invoice_data
        }
        
    except Exception as e:
        logger.exception(f"Error parsing invoice with Eyelevel: {str(e)}")
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
