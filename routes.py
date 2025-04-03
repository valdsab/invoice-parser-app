import os
import json
import logging
import tempfile
import datetime
from typing import Optional
from werkzeug.utils import secure_filename
from flask import (
    render_template, request, jsonify, send_from_directory, 
    redirect, url_for, flash, session, current_app
)
import requests

from app import app, db
from models import Invoice, InvoiceLineItem, VendorMapping
from utils import allowed_file, parse_invoice, create_zoho_vendor_bill, get_vendor_mapping

logger = logging.getLogger(__name__)

@app.route('/')
def index():
    """Render the main application page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_invoice():
    """Handle invoice file upload and initial processing"""
    if 'invoice' not in request.files:
        return jsonify({'success': False, 'error': 'No file part'}), 400
    
    file = request.files['invoice']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'}), 400
    
    # Enhanced MIME type validation
    filename = secure_filename(file.filename)
    mime_type = file.content_type
    
    # Log attempt information
    logger.info(f"Upload attempt: {filename}, MIME type: {mime_type}")
    
    if not allowed_file(filename, mime_type):
        return jsonify({
            'success': False, 
            'error': 'File type not allowed. Only PDF, JPEG, and PNG files are supported.'
        }), 400
    
    # Save uploaded file to temporary location
    file_path: Optional[str] = None
    try:
        # Create a secure filename to prevent path traversal attacks
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
        
        # Parse invoice with LlamaCloud
        logger.debug(f"Sending invoice {invoice.id} to LlamaCloud OCR API: {file_path}")
        parse_result = parse_invoice(file_path)
        
        if parse_result['success']:
            # Update invoice with parsed data
            invoice_data = parse_result['data']
            
            # Get raw extraction data
            raw_data = {}
            data_source_type = "extraction"
            
            # Get LlamaCloud raw data
            raw_data = parse_result.get('raw_extraction_data', {}) 
            logger.debug(f"Invoice {invoice.id} parsed with LlamaCloud")
            
            if not raw_data:
                # No raw data found
                logger.warning(f"No raw data found in parse result for invoice {invoice.id}")
            logger.debug(f"OCR success for invoice {invoice.id}. Raw data: {json.dumps(invoice_data, indent=2)}")
            
            vendor_name = invoice_data.get('vendor_name')
            invoice.vendor_name = vendor_name
            invoice.invoice_number = invoice_data.get('invoice_number')
            
            # Try to find and associate a vendor mapping if available
            if vendor_name:
                # Try exact match first
                vendor_mapping = VendorMapping.query.filter(
                    VendorMapping.vendor_name == vendor_name,
                    VendorMapping.is_active == True
                ).first()
                
                # If no exact match, try case-insensitive match
                if not vendor_mapping:
                    vendor_mappings = VendorMapping.query.filter(
                        VendorMapping.is_active == True
                    ).all()
                    
                    for mapping in vendor_mappings:
                        if mapping.vendor_name.lower() == vendor_name.lower():
                            vendor_mapping = mapping
                            break
                
                if vendor_mapping:
                    invoice.vendor_mapping_id = vendor_mapping.id
                    logger.debug(f"Associated invoice with vendor mapping {vendor_mapping.id} for {vendor_name}")
            
            # Parse dates
            invoice_date = invoice_data.get('invoice_date')
            if invoice_date and isinstance(invoice_date, str):
                try:
                    invoice.invoice_date = datetime.datetime.strptime(invoice_date, '%Y-%m-%d').date()
                    logger.debug(f"Parsed invoice date: {invoice.invoice_date}")
                except ValueError:
                    logger.error(f"Invalid invoice date format: {invoice_date}")
            
            due_date = invoice_data.get('due_date')
            if due_date and isinstance(due_date, str):
                try:
                    invoice.due_date = datetime.datetime.strptime(due_date, '%Y-%m-%d').date()
                    logger.debug(f"Parsed due date: {invoice.due_date}")
                except ValueError:
                    logger.error(f"Invalid due date format: {due_date}")
            
            invoice.total_amount = invoice_data.get('total_amount')
            
            # Store both normalized and raw data for completeness
            parsed_data = {
                'normalized': invoice_data
            }
            
            # Store the raw extraction data (always using LlamaCloud now)
            parsed_data['raw_extraction_data'] = raw_data
            invoice.parsed_data = json.dumps(parsed_data)
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
                    tax=item_data.get('tax', 0),
                    project_number=item_data.get('project_number'),
                    project_name=item_data.get('project_name'),
                    activity_code=item_data.get('activity_code')
                )
                db.session.add(line_item)
            
            db.session.commit()
            logger.debug(f"Invoice {invoice.id} successfully parsed")
            
            # Return the invoice details with all extracted data in JSON format
            return jsonify({
                'success': True,
                'message': 'Invoice uploaded and parsed successfully',
                'invoice_id': invoice.id,
                'invoice_data': invoice.to_dict(),
                'line_items': [item.to_dict() for item in invoice.line_items],
                'parsed_data': invoice_data,
                'raw_extraction_data': raw_data,
                'parser_used': 'LlamaCloud'
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
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

def fix_stuck_invoices():
    """
    Fix invoices that are stuck in processing state for too long
    """
    processing_timeout = 60  # seconds
    current_time = datetime.datetime.utcnow()
    
    try:
        # Find all invoices in processing state
        stuck_invoices = Invoice.query.filter_by(status="processing").all()
        
        for invoice in stuck_invoices:
            # Calculate how long the invoice has been in processing state
            if invoice.updated_at:
                seconds_in_processing = (current_time - invoice.updated_at).total_seconds()
                
                # If processing for more than the timeout, mark as error
                if seconds_in_processing > processing_timeout:
                    logger.warning(f"Invoice {invoice.id} stuck in processing state for {int(seconds_in_processing)}s, marking as error")
                    invoice.status = "error"
                    invoice.error_message = "Processing timeout - The invoice processing took too long and was aborted."
                    db.session.commit()
            else:
                # If no updated_at timestamp, use created_at
                seconds_since_created = (current_time - invoice.created_at).total_seconds()
                if seconds_since_created > processing_timeout:
                    logger.warning(f"Invoice {invoice.id} stuck in processing state since creation {int(seconds_since_created)}s ago, marking as error")
                    invoice.status = "error"
                    invoice.error_message = "Processing timeout - The invoice processing took too long and was aborted."
                    db.session.commit()
    except Exception as e:
        logger.exception(f"Error checking for stuck invoices: {str(e)}")
        # Don't raise exception as this is just a helper function

@app.route('/invoices', methods=['GET'])
def list_invoices():
    """Get list of all processed invoices with option to include detailed data"""
    try:
        # Check for and fix any invoices stuck in processing state
        fix_stuck_invoices()
        
        # Optional parameter to include line items and parsed data
        include_details = request.args.get('include_details', 'false').lower() == 'true'
        
        invoices = Invoice.query.order_by(Invoice.created_at.desc()).all()
        
        # Basic response with invoice data
        response = {
            'invoices': [invoice.to_dict() for invoice in invoices]
        }
        
        # Add line items and parsed data if requested
        if include_details:
            invoice_details = []
            for invoice in invoices:
                invoice_data = invoice.to_dict()
                
                # Add line items
                invoice_data['line_items'] = [item.to_dict() for item in invoice.line_items]
                
                # Add parsed data if available
                if invoice.parsed_data:
                    try:
                        stored_data = json.loads(invoice.parsed_data)
                        if isinstance(stored_data, dict):
                            if 'normalized' in stored_data:
                                invoice_data['parsed_data'] = stored_data.get('normalized', {})
                                invoice_data['raw_extraction_data'] = stored_data.get('raw_extraction_data', {})
                            else:
                                invoice_data['parsed_data'] = stored_data
                    except json.JSONDecodeError:
                        pass
                
                invoice_details.append(invoice_data)
            
            response['invoices'] = invoice_details
        
        return jsonify(response)
    except Exception as e:
        logger.exception(f"Error listing invoices: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/invoices/<int:invoice_id>', methods=['GET'])
def get_invoice(invoice_id):
    """Get details of a specific invoice"""
    invoice = Invoice.query.get_or_404(invoice_id)
    line_items = [item.to_dict() for item in invoice.line_items]
    
    # Parse the stored JSON data
    parsed_data = {}
    raw_data = {}
    raw_data_type = "extraction"  # Now we only use LlamaCloud extraction
    
    if invoice.parsed_data:
        try:
            logger.debug(f"Parsing stored JSON data for invoice {invoice_id}: {invoice.parsed_data[:100]}...")
            stored_data = json.loads(invoice.parsed_data)
            logger.debug(f"JSON parsed successfully. Structure: {list(stored_data.keys()) if isinstance(stored_data, dict) else 'Not a dict'}")
            
            if isinstance(stored_data, dict):
                # Check if data is in the newer formats
                if 'normalized' in stored_data:
                    parsed_data = stored_data.get('normalized', {})
                    logger.debug(f"Found normalized data structure. Keys: {list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'Not a dict'}")
                    
                    # Get raw extraction data if present
                    if 'raw_extraction_data' in stored_data:
                        raw_data = stored_data.get('raw_extraction_data', {})
                        logger.debug(f"Found raw_extraction_data in stored_data. Type: {type(raw_data)}")
                    else:
                        logger.debug("No raw_extraction_data found in stored_data")
                else:
                    # Old format - the entire stored_data is the normalized data
                    parsed_data = stored_data
                    logger.debug("Using old format - entire stored_data is normalized data")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON data stored for invoice {invoice_id}: {str(e)}")
    
    # Always include raw data by default
    response_data = {
        'invoice': invoice.to_dict(),
        'line_items': line_items,
        'parsed_data': parsed_data,  # Include the normalized parsed data
        'raw_extraction_data': raw_data,  # Always include raw extraction data
        'parser_used': "LlamaCloud"
    }
    
    return jsonify(response_data)

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

# Vendor Mapping Routes
@app.route('/vendor-mappings', methods=['GET'])
def list_vendor_mappings():
    """Get list of all vendor mappings"""
    try:
        vendor_mappings = VendorMapping.query.order_by(VendorMapping.vendor_name).all()
        return jsonify({
            'vendor_mappings': [mapping.to_dict() for mapping in vendor_mappings]
        })
    except Exception as e:
        logger.exception(f"Error listing vendor mappings: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/vendor-mappings/<int:mapping_id>', methods=['GET'])
def get_vendor_mapping_by_id(mapping_id):
    """Get a specific vendor mapping by ID"""
    try:
        mapping = VendorMapping.query.get_or_404(mapping_id)
        return jsonify({
            'vendor_mapping': mapping.to_dict()
        })
    except Exception as e:
        logger.exception(f"Error getting vendor mapping {mapping_id}: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/vendor-mappings', methods=['POST'])
def create_vendor_mapping():
    """Create a new vendor mapping"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('vendor_name'):
            return jsonify({
                'success': False,
                'message': 'Vendor name is required'
            }), 400
            
        # Check if vendor mapping already exists
        existing_mapping = VendorMapping.query.filter_by(
            vendor_name=data['vendor_name']
        ).first()
        
        if existing_mapping:
            return jsonify({
                'success': False,
                'message': f'Vendor mapping for {data["vendor_name"]} already exists'
            }), 400
        
        # Create mapping with proper JSON serialization
        field_mappings = data.get('field_mappings')
        regex_patterns = data.get('regex_patterns')
        
        # Validate and serialize JSON
        if field_mappings and not isinstance(field_mappings, str):
            field_mappings = json.dumps(field_mappings)
            
        if regex_patterns and not isinstance(regex_patterns, str):
            regex_patterns = json.dumps(regex_patterns)
        
        # Create new mapping
        new_mapping = VendorMapping(
            vendor_name=data['vendor_name'],
            field_mappings=field_mappings,
            regex_patterns=regex_patterns,
            is_active=data.get('is_active', True)
        )
        
        db.session.add(new_mapping)
        db.session.commit()
        
        logger.debug(f"Created vendor mapping for {data['vendor_name']}")
        
        return jsonify({
            'success': True,
            'message': f'Vendor mapping for {data["vendor_name"]} created successfully',
            'vendor_mapping': new_mapping.to_dict()
        })
        
    except Exception as e:
        logger.exception(f"Error creating vendor mapping: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error creating vendor mapping: {str(e)}'
        }), 500

@app.route('/vendor-mappings/<int:mapping_id>', methods=['PUT'])
def update_vendor_mapping(mapping_id):
    """Update an existing vendor mapping"""
    try:
        mapping = VendorMapping.query.get_or_404(mapping_id)
        data = request.get_json()
        
        # Update fields if provided
        if 'vendor_name' in data:
            # Check if new vendor name would create a duplicate
            if data['vendor_name'] != mapping.vendor_name:
                existing = VendorMapping.query.filter_by(
                    vendor_name=data['vendor_name']
                ).first()
                
                if existing and existing.id != mapping_id:
                    return jsonify({
                        'success': False,
                        'message': f'Vendor mapping for {data["vendor_name"]} already exists'
                    }), 400
                    
            mapping.vendor_name = data['vendor_name']
        
        # Update and serialize field mappings if provided
        if 'field_mappings' in data:
            if data['field_mappings'] and not isinstance(data['field_mappings'], str):
                mapping.field_mappings = json.dumps(data['field_mappings'])
            else:
                mapping.field_mappings = data['field_mappings']
        
        # Update and serialize regex patterns if provided
        if 'regex_patterns' in data:
            if data['regex_patterns'] and not isinstance(data['regex_patterns'], str):
                mapping.regex_patterns = json.dumps(data['regex_patterns'])
            else:
                mapping.regex_patterns = data['regex_patterns']
        
        # Update active status if provided
        if 'is_active' in data:
            mapping.is_active = data['is_active']
        
        mapping.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        
        logger.debug(f"Updated vendor mapping {mapping_id} for {mapping.vendor_name}")
        
        return jsonify({
            'success': True,
            'message': f'Vendor mapping for {mapping.vendor_name} updated successfully',
            'vendor_mapping': mapping.to_dict()
        })
        
    except Exception as e:
        logger.exception(f"Error updating vendor mapping {mapping_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error updating vendor mapping: {str(e)}'
        }), 500

@app.route('/vendor-mappings/<int:mapping_id>', methods=['DELETE'])
def delete_vendor_mapping(mapping_id):
    """Delete a vendor mapping"""
    try:
        mapping = VendorMapping.query.get_or_404(mapping_id)
        vendor_name = mapping.vendor_name
        
        db.session.delete(mapping)
        db.session.commit()
        
        logger.debug(f"Deleted vendor mapping {mapping_id} for {vendor_name}")
        
        return jsonify({
            'success': True,
            'message': f'Vendor mapping for {vendor_name} deleted successfully'
        })
        
    except Exception as e:
        logger.exception(f"Error deleting vendor mapping {mapping_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error deleting vendor mapping: {str(e)}'
        }), 500

@app.route('/invoices/<int:invoice_id>/apply-mapping/<int:mapping_id>', methods=['POST'])
def apply_vendor_mapping_to_invoice(invoice_id, mapping_id):
    """Apply a vendor mapping to an existing invoice and reparse it"""
    try:
        invoice = Invoice.query.get_or_404(invoice_id)
        mapping = VendorMapping.query.get_or_404(mapping_id)
        
        # Log the mapping attempt with detailed information
        logger.info(f"Applying vendor mapping {mapping_id} ({mapping.vendor_name}) to invoice {invoice_id}")
        
        # Update the invoice with the mapping ID
        invoice.vendor_mapping_id = mapping.id
        db.session.commit()
        
        # If the invoice has parsed data, reapply the mapping
        if invoice.parsed_data and invoice.status in ['parsed', 'completed']:
            try:
                # Parse the stored data
                stored_data = json.loads(invoice.parsed_data)
                raw_extraction_data = {}
                
                # Extract the raw data based on source
                if isinstance(stored_data, dict):
                    if 'raw_extraction_data' in stored_data:
                        raw_extraction_data = stored_data.get('raw_extraction_data', {})
                    # Legacy format from older version - kept for backward compatibility
                    elif 'raw_xray' in stored_data:
                        raw_extraction_data = stored_data.get('raw_xray', {})
                    
                # Re-normalize the data with the new mapping
                if not raw_extraction_data:
                    # Skip processing for unsupported or legacy data format
                    logger.warning(f"Skipping unsupported data format for invoice {invoice_id}")
                    return jsonify({
                        'success': False,
                        'error': 'Unsupported data format cannot be reprocessed'
                    }), 400
                
                # Prepare data for normalization
                from utils import transform_llama_cloud_to_invoice_format, normalize_invoice
                
                # Process data with LlamaCloud - Transform the extraction data
                transformed_data = transform_llama_cloud_to_invoice_format(raw_extraction_data, invoice.file_name)
                
                # Force the vendor name to match our mapping
                if transformed_data and isinstance(transformed_data, dict) and 'vendor' in transformed_data:
                    transformed_data['vendor']['name'] = mapping.vendor_name
                
                # Normalize the transformed data with the new mapping
                normalized_data = normalize_invoice(transformed_data)
                
                # Update invoice with newly normalized data
                if normalized_data:
                    # Update invoice fields
                    invoice.vendor_name = normalized_data.get('vendor_name')
                    invoice.invoice_number = normalized_data.get('invoice_number')
                    
                    # Parse dates
                    invoice_date = normalized_data.get('invoice_date')
                    if invoice_date and isinstance(invoice_date, str):
                        try:
                            invoice.invoice_date = datetime.datetime.strptime(
                                invoice_date, '%Y-%m-%d'
                            ).date()
                        except ValueError:
                            logger.warning(f"Invalid invoice date format: {invoice_date}")
                    
                    due_date = normalized_data.get('due_date')
                    if due_date and isinstance(due_date, str):
                        try:
                            invoice.due_date = datetime.datetime.strptime(
                                due_date, '%Y-%m-%d'
                            ).date()
                        except ValueError:
                            logger.warning(f"Invalid due date format: {due_date}")
                    
                    invoice.total_amount = normalized_data.get('total_amount')
                    
                    # Store updated data                 
                    # Store the updated data
                    updated_parsed_data = {
                        'normalized': normalized_data,
                        'raw_extraction_data': raw_extraction_data
                    }
                    invoice.parsed_data = json.dumps(updated_parsed_data)
                    
                    # Update line items
                    # First delete existing line items
                    InvoiceLineItem.query.filter_by(invoice_id=invoice.id).delete()
                    
                    # Then add new ones
                    line_items = normalized_data.get('line_items', [])
                    for item_data in line_items:
                        line_item = InvoiceLineItem(
                            invoice_id=invoice.id,
                            description=item_data.get('description'),
                            quantity=item_data.get('quantity'),
                            unit_price=item_data.get('unit_price'),
                            amount=item_data.get('amount'),
                            tax=item_data.get('tax', 0),
                            project_number=item_data.get('project_number'),
                            project_name=item_data.get('project_name'),
                            activity_code=item_data.get('activity_code')
                        )
                        db.session.add(line_item)
                    
                    db.session.commit()
                    
                    # Always using LlamaCloud now
                    parser_used = "LlamaCloud"
                        
                    logger.info(f"Successfully applied vendor mapping with {parser_used} parser data")
                    
                    return jsonify({
                        'success': True,
                        'message': f'Vendor mapping for {mapping.vendor_name} applied to invoice {invoice_id}',
                        'invoice': invoice.to_dict(),
                        'line_items': [item.to_dict() for item in invoice.line_items],
                        'parsed_data': normalized_data,
                        'raw_extraction_data': raw_extraction_data,
                        'parser_used': parser_used
                    })
            except Exception as parse_error:
                logger.exception(f"Error reparsing invoice data: {str(parse_error)}")
                return jsonify({
                    'success': False,
                    'message': f'Error reparsing invoice data: {str(parse_error)}'
                }), 500
        
        # If we get here, we either had no parsed data or had an error reparsing
        # Return success for the mapping association but note no reparse
        return jsonify({
            'success': True,
            'message': f'Vendor mapping for {mapping.vendor_name} associated with invoice {invoice_id} (no reparse)',
            'invoice': invoice.to_dict(),
            'parser_used': 'None'  # No parser was used since there was no reparse
        })
        
    except Exception as e:
        logger.exception(f"Error applying vendor mapping to invoice: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error applying vendor mapping: {str(e)}'
        }), 500
