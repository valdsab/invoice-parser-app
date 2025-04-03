import logging
import os
import psycopg2
from psycopg2 import sql

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """
    Run database migration to:
    1. Add new columns to invoice_line_item table
    2. Create vendor_mapping table
    3. Add vendor_mapping_id column to invoice table
    """
    # Get database connection info from environment variables
    db_url = os.environ.get('DATABASE_URL')
    
    if not db_url:
        logger.error("DATABASE_URL environment variable not found")
        return False
    
    try:
        # Connect to the database
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        cursor = conn.cursor()
        
        # Part 1: Check if invoice_line_item table has the required columns
        cursor.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name = 'invoice_line_item'
        """)
        columns = [column[0] for column in cursor.fetchall()]
        
        # Add new columns if they don't exist
        if columns:  # If the table exists
            new_columns = []
            if 'project_number' not in columns:
                new_columns.append(('project_number', 'VARCHAR(100)'))
            
            if 'project_name' not in columns:
                new_columns.append(('project_name', 'VARCHAR(255)'))
                
            if 'activity_code' not in columns:
                new_columns.append(('activity_code', 'VARCHAR(100)'))
            
            # Execute ALTER TABLE statements for each new column
            for column_name, column_type in new_columns:
                logger.info(f"Adding column {column_name} to invoice_line_item table")
                cursor.execute(
                    sql.SQL("ALTER TABLE invoice_line_item ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(column_name), sql.SQL(column_type)
                    )
                )
        else:
            logger.info("invoice_line_item table does not exist yet, skipping column additions")
        
        # Part 2: Create vendor_mapping table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_mapping (
            id SERIAL PRIMARY KEY,
            vendor_name VARCHAR(255) NOT NULL UNIQUE,
            field_mappings TEXT,
            regex_patterns TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
        """)
        logger.info("Created vendor_mapping table if it didn't exist")
        
        # Part 3: Check if invoice table has vendor_mapping_id column
        cursor.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name = 'invoice' AND column_name = 'vendor_mapping_id'
        """)
        has_mapping_column = cursor.fetchone() is not None
        
        if not has_mapping_column:
            logger.info("Adding vendor_mapping_id column to invoice table")
            cursor.execute("""
            ALTER TABLE invoice ADD COLUMN IF NOT EXISTS vendor_mapping_id INTEGER REFERENCES vendor_mapping(id)
            """)
        
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