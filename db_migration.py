import sqlite3
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """
    Run database migration to:
    1. Add new columns to invoice_line_item table
    2. Create vendor_mapping table
    3. Add vendor_mapping_id column to invoice table
    """
    # Database path in instance folder
    db_path = os.path.join('instance', 'invoice_parser.db')
    
    if not os.path.exists(db_path):
        logger.error(f"Database file not found at {db_path}")
        return False
    
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Part 1: Add columns to invoice_line_item
        cursor.execute("PRAGMA table_info(invoice_line_item)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add new columns if they don't exist
        new_columns = []
        if 'project_number' not in columns:
            new_columns.append(('project_number', 'TEXT'))
        
        if 'project_name' not in columns:
            new_columns.append(('project_name', 'TEXT'))
            
        if 'activity_code' not in columns:
            new_columns.append(('activity_code', 'TEXT'))
        
        # Execute ALTER TABLE statements for each new column
        for column_name, column_type in new_columns:
            logger.info(f"Adding column {column_name} to invoice_line_item table")
            cursor.execute(f"ALTER TABLE invoice_line_item ADD COLUMN {column_name} {column_type}")
        
        # Part 2: Create vendor_mapping table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_name TEXT NOT NULL UNIQUE,
            field_mappings TEXT,
            regex_patterns TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
        """)
        logger.info("Created vendor_mapping table if it didn't exist")
        
        # Part 3: Add vendor_mapping_id column to invoice table if it doesn't exist
        cursor.execute("PRAGMA table_info(invoice)")
        invoice_columns = [column[1] for column in cursor.fetchall()]
        
        if 'vendor_mapping_id' not in invoice_columns:
            logger.info("Adding vendor_mapping_id column to invoice table")
            cursor.execute("ALTER TABLE invoice ADD COLUMN vendor_mapping_id INTEGER REFERENCES vendor_mapping(id)")
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        
        logger.info("Database migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error during database migration: {str(e)}")
        return False

if __name__ == "__main__":
    run_migration()