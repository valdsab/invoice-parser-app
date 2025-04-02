import os
import json
import logging
import tempfile
import datetime
from werkzeug.utils import secure_filename
from flask import (
    render_template, request, jsonify, send_from_directory, 
    redirect, url_for, flash, session, current_app
)
import requests

from app import app, db
from models import Invoice, InvoiceLineItem
from utils import allowed_file, parse_invoice_with_eyelevel, create_zoho_vendor_bill

logger = logging.getLogger(__name__)

@app.route('/')
def index():
    """Render the main application page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_invoice():
    """Handle invoice file upload and initial processing"""
    if 'invoice' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['invoice']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Save uploaded file to temporary location
    try:
        filename = secure_filename(file.filename)
        file_path = os.path.join(tempfile.gettempdir(), filename)
        file.save(file_path)
        
        # Create database record
        invoice = Invoice(
            file_name=filename,
            status="uploaded"
        )
        db.session.add(invoice)
        db.session.commit()
        
        # Start processing
        invoice.status = "processing"
        db.session.commit()
        
        logger.debug(f"Processing invoice {invoice.id} - {filename}")
        
        # Parse invoice with Eyelevel.ai
        logger.debug(f"Sending invoice {invoice.id} to Eyelevel.ai OCR API: {file_path}")
        parse_result = parse_invoice_with_eyelevel(file_path)
        
        if parse_result['success']:
            # Update invoice with parsed data
            invoice_data = parse_result['data']
            logger.debug(f"OCR success for invoice {invoice.id}. Raw data: {json.dumps(invoice_data, indent=2)}")
            
            invoice.vendor_name = invoice_data.get('vendor_name')
            invoice.invoice_number = invoice_data.get('invoice_number')
            
            # Parse dates
            if invoice_data.get('invoice_date'):
                try:
                    invoice.invoice_date = datetime.datetime.strptime(
                        invoice_data.get('invoice_date'), '%Y-%m-%d'
                    ).date()
                    logger.debug(f"Parsed invoice date: {invoice.invoice_date}")
                except ValueError:
                    logger.error(f"Invalid invoice date format: {invoice_data.get('invoice_date')}")
            
            if invoice_data.get('due_date'):
                try:
                    invoice.due_date = datetime.datetime.strptime(
                        invoice_data.get('due_date'), '%Y-%m-%d'
                    ).date()
                    logger.debug(f"Parsed due date: {invoice.due_date}")
                except ValueError:
                    logger.error(f"Invalid due date format: {invoice_data.get('due_date')}")
            
            invoice.total_amount = invoice_data.get('total_amount')
            invoice.parsed_data = json.dumps(invoice_data)
            invoice.status = "parsed"
            
            # Add line items
            line_items = invoice_data.get('line_items', [])
            for item_data in line_items:
                line_item = InvoiceLineItem(
                    invoice_id=invoice.id,
                    description=item_data.get('description'),
                    quantity=item_data.get('quantity'),
                    unit_price=item_data.get('unit_price'),
                    amount=item_data.get('amount'),
                    tax=item_data.get('tax', 0)
                )
                db.session.add(line_item)
            
            db.session.commit()
            logger.debug(f"Invoice {invoice.id} successfully parsed")
            
            return jsonify({
                'success': True,
                'message': 'Invoice uploaded and parsed successfully',
                'invoice_id': invoice.id,
                'invoice_data': invoice.to_dict()
            })
        else:
            # Update invoice with error
            invoice.status = "error"
            invoice.error_message = parse_result['error']
            db.session.commit()
            logger.error(f"Error parsing invoice {invoice.id}: {parse_result['error']}")
            
            return jsonify({
                'success': False,
                'message': 'Error parsing invoice',
                'error': parse_result['error'],
                'invoice_id': invoice.id
            }), 400
            
    except Exception as e:
        logger.exception(f"Error processing invoice: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        # Clean up temporary file
        if os.path.exists(file_path):
            os.remove(file_path)

@app.route('/invoices', methods=['GET'])
def list_invoices():
    """Get list of all processed invoices"""
    invoices = Invoice.query.order_by(Invoice.created_at.desc()).all()
    return jsonify({
        'invoices': [invoice.to_dict() for invoice in invoices]
    })

@app.route('/invoices/<int:invoice_id>', methods=['GET'])
def get_invoice(invoice_id):
    """Get details of a specific invoice"""
    invoice = Invoice.query.get_or_404(invoice_id)
    line_items = [item.to_dict() for item in invoice.line_items]
    
    return jsonify({
        'invoice': invoice.to_dict(),
        'line_items': line_items
    })

@app.route('/create_vendor_bill/<int:invoice_id>', methods=['POST'])
def create_vendor_bill(invoice_id):
    """Create vendor bill in Zoho Books using parsed invoice data"""
    invoice = Invoice.query.get_or_404(invoice_id)
    
    if invoice.status != 'parsed':
        return jsonify({
            'success': False,
            'message': f'Cannot create vendor bill. Invoice status is {invoice.status}'
        }), 400
    
    # Since we're skipping Zoho integration for now, just mark it as completed
    try:
        # Update invoice status
        invoice.status = "completed"
        invoice.zoho_vendor_bill_id = "TEST-VENDOR-BILL-ID-" + str(invoice.id)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'OCR testing completed - Zoho integration skipped',
            'vendor_bill_id': invoice.zoho_vendor_bill_id,
            'invoice_id': invoice.id
        })
            
    except Exception as e:
        logger.exception(f"Error creating vendor bill: {str(e)}")
        invoice.error_message = str(e)
        db.session.commit()
        
        return jsonify({
            'success': False,
            'message': 'Error creating vendor bill',
            'error': str(e),
            'invoice_id': invoice.id
        }), 500

@app.route('/invoices/<int:invoice_id>', methods=['DELETE'])
def delete_invoice(invoice_id):
    """Delete an invoice and its line items"""
    try:
        invoice = Invoice.query.get_or_404(invoice_id)
        
        # Delete related line items first
        InvoiceLineItem.query.filter_by(invoice_id=invoice_id).delete()
        
        # Delete the invoice
        db.session.delete(invoice)
        db.session.commit()
        
        logger.debug(f"Invoice {invoice_id} deleted successfully")
        
        return jsonify({
            'success': True,
            'message': f'Invoice {invoice_id} deleted successfully'
        })
    except Exception as e:
        logger.exception(f"Error deleting invoice {invoice_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error deleting invoice: {str(e)}'
        }), 500

@app.route('/invoices/delete-multiple', methods=['POST'])
def delete_multiple_invoices():
    """Delete multiple invoices"""
    try:
        data = request.get_json()
        invoice_ids = data.get('invoice_ids', [])
        
        if not invoice_ids:
            return jsonify({
                'success': False,
                'message': 'No invoice IDs provided'
            }), 400
        
        # Delete related line items first
        for invoice_id in invoice_ids:
            InvoiceLineItem.query.filter_by(invoice_id=invoice_id).delete()
        
        # Delete the invoices
        deleted_count = Invoice.query.filter(Invoice.id.in_(invoice_ids)).delete(synchronize_session=False)
        db.session.commit()
        
        logger.debug(f"Deleted {deleted_count} invoices: {invoice_ids}")
        
        return jsonify({
            'success': True,
            'message': f'{deleted_count} invoices deleted successfully'
        })
    except Exception as e:
        logger.exception(f"Error deleting multiple invoices: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error deleting invoices: {str(e)}'
        }), 500

@app.route('/deluge_script', methods=['GET'])
def get_deluge_script():
    """Retrieve the Deluge script for Zoho integration"""
    return render_template('deluge_script.txt')
