from app import db
import datetime

class VendorMapping(db.Model):
    """Model for storing vendor-specific field mappings"""
    id = db.Column(db.Integer, primary_key=True)
    vendor_name = db.Column(db.String(255), nullable=False, unique=True)
    field_mappings = db.Column(db.Text)  # JSON data for field mappings
    regex_patterns = db.Column(db.Text)  # JSON data for custom regex patterns
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'vendor_name': self.vendor_name,
            'field_mappings': self.field_mappings,
            'regex_patterns': self.regex_patterns,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Invoice(db.Model):
    """Model for storing invoice information"""
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default="uploaded")  # uploaded, processing, parsed, error, completed
    vendor_name = db.Column(db.String(255))
    vendor_mapping_id = db.Column(db.Integer, db.ForeignKey('vendor_mapping.id'), nullable=True)
    invoice_number = db.Column(db.String(100))
    invoice_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    total_amount = db.Column(db.Float)
    parsed_data = db.Column(db.Text)  # JSON data
    error_message = db.Column(db.Text)
    zoho_vendor_bill_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.datetime.utcnow)
    
    # Relationship to the vendor mapping
    vendor_mapping = db.relationship('VendorMapping', backref=db.backref('invoices', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'file_name': self.file_name,
            'status': self.status,
            'vendor_name': self.vendor_name,
            'vendor_mapping_id': self.vendor_mapping_id,
            'invoice_number': self.invoice_number,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'total_amount': self.total_amount,
            'zoho_vendor_bill_id': self.zoho_vendor_bill_id,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class InvoiceLineItem(db.Model):
    """Model for storing invoice line items"""
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    description = db.Column(db.Text)
    quantity = db.Column(db.Float)
    unit_price = db.Column(db.Float)
    amount = db.Column(db.Float)
    tax = db.Column(db.Float)
    project_number = db.Column(db.String(100))
    project_name = db.Column(db.String(255)) 
    activity_code = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    invoice = db.relationship('Invoice', backref=db.backref('line_items', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'description': self.description,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'amount': self.amount,
            'tax': self.tax,
            'project_number': self.project_number,
            'project_name': self.project_name,
            'activity_code': self.activity_code
        }
