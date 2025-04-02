import sqlite3
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """
    Run database migration to add new columns to invoice_line_item table
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
        
        # Check if columns already exist
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
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        
        if new_columns:
            logger.info("Database migration completed successfully")
        else:
            logger.info("No migration needed, columns already exist")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during database migration: {str(e)}")
        return False

if __name__ == "__main__":
    run_migration()