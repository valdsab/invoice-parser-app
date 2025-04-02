import os
import json
import logging
import requests
from app import app

logger = logging.getLogger(__name__)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def parse_invoice_with_eyelevel(file_path):
    """
    Use Eyelevel.ai API to parse an invoice
    
    Args:
        file_path: Path to the invoice file
        
    Returns:
        dict: Result with parsed data or error message
    """
    try:
        # Get API key from environment
        api_key = os.environ.get("EYELEVEL_API_KEY")
        if not api_key:
            logger.error("EYELEVEL_API_KEY environment variable not set")
            return {
                'success': False,
                'error': 'Eyelevel API key not configured'
            }
        
        # API endpoint for document parsing - using Eyelevel OCR API
        url = "https://api.eyelevel.ai/v1/document/parse"
        
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        logger.debug(f"Sending file {file_path} to Eyelevel.ai API")
        
        # Open the file and submit to Eyelevel API
        with open(file_path, 'rb') as file:
            files = {'file': file}
            response = requests.post(url, headers=headers, files=files)
            
        logger.debug(f"Eyelevel.ai API response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Eyelevel API error: {response.status_code} - {response.text}")
            return {
                'success': False,
                'error': f"Eyelevel API error: {response.status_code} - {response.text}"
            }
            
        # Parse the response
        response_data = response.json()
        logger.debug(f"Eyelevel.ai API raw response: {json.dumps(response_data, indent=2)}")
        
        # Extract relevant invoice data
        invoice_data = {
            'vendor_name': response_data.get('vendor', {}).get('name'),
            'invoice_number': response_data.get('invoice_number'),
            'invoice_date': response_data.get('date'),
            'due_date': response_data.get('due_date'),
            'total_amount': float(response_data.get('total_amount', 0)),
            'line_items': [],
            'raw_response': response_data  # Include the full response for debugging
        }
        
        # Extract line items
        for item in response_data.get('line_items', []):
            line_item = {
                'description': item.get('description'),
                'quantity': float(item.get('quantity', 1)),
                'unit_price': float(item.get('unit_price', 0)),
                'amount': float(item.get('amount', 0)),
                'tax': float(item.get('tax', 0))
            }
            invoice_data['line_items'].append(line_item)
        
        logger.debug(f"Extracted invoice data: {json.dumps(invoice_data, indent=2)}")
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

def create_zoho_vendor_bill(invoice, line_items):
    """
    Create a vendor bill in Zoho Books using Deluge script
    
    Args:
        invoice: Invoice model object
        line_items: List of line item dictionaries
        
    Returns:
        dict: Result with vendor bill ID or error message
    """
    try:
        # Get API key from environment
        api_key = os.environ.get("ZOHO_API_KEY")
        if not api_key:
            logger.error("ZOHO_API_KEY environment variable not set")
            return {
                'success': False,
                'error': 'Zoho API key not configured'
            }
            
        # API endpoint for Zoho Books
        url = "https://books.zoho.com/api/v3/vendorbills"
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {api_key}",
            "Content-Type": "application/json"
        }
        
        # Prepare vendor bill data
        vendor_bill_data = {
            "vendor_id": "",  # Will be looked up by name in Deluge script
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
        
        # Call Zoho Books API with Deluge script for custom processing
        response = requests.post(
            url, 
            headers=headers,
            json=vendor_bill_data
        )
        
        if response.status_code != 201:
            logger.error(f"Zoho API error: {response.status_code} - {response.text}")
            return {
                'success': False,
                'error': f"Zoho API error: {response.status_code} - {response.text}"
            }
        
        # Parse the response
        response_data = response.json()
        vendor_bill_id = response_data.get('vendorbill', {}).get('vendor_bill_id')
        
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
