from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import mysql.connector
from dotenv import load_dotenv
import os
import json
import time
from datetime import datetime
import atexit
import signal

load_dotenv()

app = Flask(__name__)
CORS(app)  

db_context = {
    "current_database": None,
    "tables": {},
    "last_query": None,
    "last_result": None
}

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "rambok"
}

# Add these at the top with other imports
DB_CACHE_FILE = 'database_cache.json'
DB_CACHE = {}

def clear_db_cache():
    """Clear the database cache file"""
    try:
        if os.path.exists(DB_CACHE_FILE):
            os.remove(DB_CACHE_FILE)
        global DB_CACHE
        DB_CACHE = {}
    except Exception as e:
        print(f"Error clearing database cache: {e}")

def load_db_cache():
    """Load database cache from file"""
    global DB_CACHE
    if os.path.exists(DB_CACHE_FILE):
        try:
            with open(DB_CACHE_FILE, 'r') as f:
                DB_CACHE = json.load(f)
        except json.JSONDecodeError:
            DB_CACHE = {}
    return DB_CACHE

def save_db_cache():
    """Save database cache to file"""
    with open(DB_CACHE_FILE, 'w') as f:
        json.dump(DB_CACHE, f, indent=2)

def cleanup():
    """Cleanup function to be called when the application exits"""
    clear_db_cache()

# Register cleanup function
atexit.register(cleanup)

# Handle SIGTERM and SIGINT signals
def signal_handler(signum, frame):
    cleanup()
    exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Clear cache on startup
clear_db_cache()

def update_database_info(database):
    """Update database information in cache"""
    try:
        connection = get_db_connection(database)
        if not connection:
            return None

        cursor = connection.cursor()
        
        # Get all tables
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        
        # Clear the entire cache and create new entry
        global DB_CACHE
        DB_CACHE = {
            database: {
                'last_updated': datetime.now().isoformat(),
                'tables': {}
            }
        }
        
        # Get table information
        for table in tables:
            # Get table structure
            cursor.execute(f"DESCRIBE {table}")
            columns = cursor.fetchall()
            
            # Get primary keys
            cursor.execute(f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = '{database}'
                AND TABLE_NAME = '{table}'
                AND CONSTRAINT_NAME = 'PRIMARY'
            """)
            primary_keys = [row[0] for row in cursor.fetchall()]
            
            # Get foreign keys
            cursor.execute(f"""
                SELECT 
                    COLUMN_NAME,
                    REFERENCED_TABLE_NAME,
                    REFERENCED_COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = '{database}'
                AND TABLE_NAME = '{table}'
                AND REFERENCED_TABLE_NAME IS NOT NULL
            """)
            foreign_keys = cursor.fetchall()
            
            # Store table information
            DB_CACHE[database]['tables'][table] = {
                'columns': [{
                    'name': col[0],
                    'type': col[1],
                    'null': col[2],
                    'key': col[3],
                    'default': col[4],
                    'extra': col[5]
                } for col in columns],
                'primary_keys': primary_keys,
                'foreign_keys': [{
                    'column': fk[0],
                    'referenced_table': fk[1],
                    'referenced_column': fk[2]
                } for fk in foreign_keys]
            }
        
        # Save cache
        save_db_cache()
        return DB_CACHE[database]
        
    except mysql.connector.Error as err:
        print(f"Error updating database info: {err}")
        return None
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

def get_database_info(database):
    """Get database information from cache or update if needed"""
    # Load cache if not loaded
    if not DB_CACHE:
        load_db_cache()
    
    # Check if database info exists and is recent (within last 5 minutes)
    if database in DB_CACHE:
        last_updated = datetime.fromisoformat(DB_CACHE[database]['last_updated'])
        if (datetime.now() - last_updated).total_seconds() < 300:  # 5 minutes
            return DB_CACHE[database]
    
    # Update database info
    return update_database_info(database)

def update_db_context(database=None, table_info=None, query=None, result=None):
    """Update the database context with new information"""
    global db_context
    if database:
        db_context["current_database"] = database
    if table_info:
        db_context["tables"].update(table_info)
    if query:
        db_context["last_query"] = query
    if result:
        db_context["last_result"] = result

def get_db_connection(database=None):
    try:
        config = DB_CONFIG.copy()
        if database:
            config["database"] = database
        connection = mysql.connector.connect(**config)
        return connection
    except mysql.connector.Error as err:
        print(f"Error connecting to MySQL: {err}")
        return None

def get_databases():
    """Fetch list of all databases"""
    try:
        connection = get_db_connection()
        if not connection:
            return []
        
        cursor = connection.cursor()
        cursor.execute("SHOW DATABASES")
        databases = [db[0] for db in cursor.fetchall() if db[0] not in ['information_schema', 'performance_schema', 'mysql', 'sys']]
        cursor.close()
        connection.close()
        return databases
    except Exception as e:
        print(f"Error fetching databases: {e}")
        return []

def get_table_info(connection, table_name):
    """Get information about a table's structure"""
    try:
        cursor = connection.cursor()
        # First try exact match
        cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
        if cursor.fetchone():
            cursor.execute(f"DESCRIBE {table_name}")
            columns = [row[0] for row in cursor.fetchall()]
            return True, columns, table_name
        
        # If not found, try case-insensitive search
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        matching_tables = [t for t in tables if t.lower() == table_name.lower()]
        
        if matching_tables:
            actual_table = matching_tables[0]
            cursor.execute(f"DESCRIBE {actual_table}")
            columns = [row[0] for row in cursor.fetchall()]
            return True, columns, actual_table
            
        return False, None, None
    except mysql.connector.Error as err:
        print(f"Error getting table info: {err}")
        return False, None, None
    finally:
        cursor.close()

def get_current_tables(connection):
    """Get current list of tables from the database"""
    try:
        cursor = connection.cursor()
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        return tables
    except mysql.connector.Error as err:
        print(f"Error getting tables: {err}")
        return []
    finally:
        cursor.close()

def get_table_structure(connection, table_name):
    """Get detailed table structure including column names and types"""
    try:
        cursor = connection.cursor()
        cursor.execute(f"DESCRIBE {table_name}")
        columns = cursor.fetchall()
        return {col[0]: col[1] for col in columns}
    except mysql.connector.Error as err:
        print(f"Error getting table structure: {err}")
        return None
    finally:
        cursor.close()

def clean_sql_response(response_text):
    """Clean up the SQL response from the model"""
    # Convert to lowercase for case-insensitive matching
    text = response_text.lower()
    
    # Remove any explanatory text before the SQL query
    if "output:" in text:
        # Split on "output:" and take the last part
        parts = response_text.split("output:")
        if len(parts) > 1:
            response_text = parts[-1].strip()
    
    # Remove any remaining explanatory text
    if "to describe" in text:
        response_text = response_text.split("to describe")[-1].strip()
    if "you can use" in text:
        response_text = response_text.split("you can use")[-1].strip()
    if "as follows" in text:
        response_text = response_text.split("as follows")[-1].strip()
    
    # Remove comments (both single-line and multi-line)
    lines = response_text.split('\n')
    cleaned_lines = []
    in_comment = False
    
    for line in lines:
        # Handle multi-line comments
        if '/*' in line:
            in_comment = True
            line = line.split('/*')[0]
        if '*/' in line:
            in_comment = False
            line = line.split('*/')[-1]
        if in_comment:
            continue
            
        # Handle single-line comments
        if '--' in line:
            line = line.split('--')[0]
            
        # Clean up the line
        line = line.strip()
        if line:  # Only add non-empty lines
            cleaned_lines.append(line)
    
    # Join lines with proper spacing
    response_text = ' '.join(cleaned_lines)
    
    # Remove any remaining newlines and extra spaces
    response_text = ' '.join(response_text.split())
    
    return response_text

def get_table_relationships(connection, database):
    """Get relationships between tables in the database"""
    try:
        cursor = connection.cursor()
        relationships = []
        
        # Get all tables in the database
        cursor.execute(f"USE {database}")
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        
        # For each table, get its foreign keys and primary keys
        for table in tables:
            # Get primary key information
            cursor.execute(f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = '{database}'
                AND TABLE_NAME = '{table}'
                AND CONSTRAINT_NAME = 'PRIMARY'
            """)
            primary_keys = [row[0] for row in cursor.fetchall()]
            
            # Get foreign key information
            cursor.execute(f"""
                SELECT 
                    COLUMN_NAME,
                    REFERENCED_TABLE_NAME,
                    REFERENCED_COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = '{database}'
                AND TABLE_NAME = '{table}'
                AND REFERENCED_TABLE_NAME IS NOT NULL
            """)
            
            foreign_keys = cursor.fetchall()
            for fk in foreign_keys:
                relationships.append({
                    'source': table,
                    'target': fk[1],
                    'source_column': fk[0],
                    'target_column': fk[2]
                })
        
        # If no relationships found, create nodes for all tables
        if not relationships:
            for table in tables:
                relationships.append({
                    'source': table,
                    'target': table,
                    'source_column': 'id',
                    'target_column': 'id'
                })
        
        return relationships
    except mysql.connector.Error as err:
        print(f"Error getting table relationships: {err}")
        return []
    finally:
        cursor.close()

def convert_to_sql(natural_language):
    """Convert natural language to SQL using LM Studio"""
    try:
        # Get current database
        current_db = db_context["current_database"]
        if not current_db:
            raise Exception("No database selected")

        # Get database information from cache
        db_info = get_database_info(current_db)
        if not db_info:
            raise Exception("Could not get database information")

        # Prepare detailed context information
        context_info = f"Current database: {current_db}\n\n"
        context_info += "Available tables:\n"
        for table in db_info['tables']:
            context_info += f"- {table}\n"
        
        context_info += "\nDetailed table structures:\n"
        for table, info in db_info['tables'].items():
            context_info += f"\nTable: {table}\n"
            context_info += "Columns:\n"
            for col in info['columns']:
                context_info += f"- {col['name']} ({col['type']})"
                if col['key']:
                    context_info += f" [{col['key']}]"
                context_info += "\n"
            
            if info['primary_keys']:
                context_info += f"Primary keys: {', '.join(info['primary_keys'])}\n"
            
            if info['foreign_keys']:
                context_info += "Foreign keys:\n"
                for fk in info['foreign_keys']:
                    context_info += f"- {fk['column']} references {fk['referenced_table']}.{fk['referenced_column']}\n"

        # Prepare the request payload
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": f"""You are a SQL expert. Convert the following natural language request into a valid SQL query.
                    CRITICAL: Return ONLY the raw SQL query without ANY text, prefixes, comments, or explanations.
                    
                    Current Database Context:
                    {context_info}
                    
                    Rules:
                    1. Return ONLY the SQL query - no prefixes, no comments, no explanations
                    2. Do not include words like 'Output:', 'Query:', or any other text
                    3. Use proper SQL syntax
                    4. CRITICAL: Use ONLY the column names that exist in the tables as shown above
                    5. For SELECT queries:
                       - Use EXACT column names from the table structures
                       - For joins, use the correct column names from both tables
                       - For conditions, use the exact column names shown above
                    6. CRITICAL TABLE NAME RULES:
                       - Use EXACT table names as specified in the request
                       - DO NOT add 's' to table names unless explicitly specified
                       - DO NOT modify table names in any way
                    7. For showing tables:
                       - If the request is to show all tables, use 'SHOW TABLES'
                       - If the request is to show a specific table, use 'SHOW TABLES LIKE table_name'
                       - If the request is to describe a table, use 'DESCRIBE table_name'
                    8. For relationships between tables:
                        - Use the exact column names from the table structures
                        - Ensure the join conditions use the correct column names
                        - Check the table structures above for the correct column names to join on
                        - Use the relationships information provided above for JOIN conditions
                    9. CRITICAL: Do not include any comments in the SQL query
                    10. CRITICAL: Do not use table aliases unless explicitly requested
                    11. For queries involving multiple tables:
                        - Always use the relationships information provided above
                        - Join tables using the correct foreign key relationships
                        - Use the exact column names for join conditions
                        - Ensure the query follows the logical flow of relationships
                    12. CRITICAL JOIN RULES:
                        - Use ONLY the foreign key relationships shown in the context
                        - For each table, check its foreign keys in the context
                        - Use the exact column names from the foreign key relationships
                        - DO NOT assume column names - use only what's shown in the context
                        - The customer table has a car_id column that references the cars table's id column
                        - When joining customer and cars tables, use customer.car_id = cars.id
                    
                    Examples:
                    Input: "show all tables" or "show tables" or "list tables" or "show table"
                    Output: SHOW TABLES;
                    
                    Input: "describe the table products"
                    Output: DESCRIBE products;
                    
                    Input: "delete the table orders"
                    Output: DROP TABLE orders;
                    
                    Input: "find the name of customer who owns a ford car"
                    Output: SELECT customer.name FROM customer JOIN cars ON customer.car_id = cars.id WHERE cars.brand = 'ford';
                    
                    Now convert this request: {natural_language}"""
                }
            ],
            "temperature": 0.05,
            "max_tokens": 500,
            "stream": False,
            "top_p": 0.1,
            "frequency_penalty": 0.5,
            "presence_penalty": 0.5
        }
        
        response = requests.post(
            "http://127.0.0.1:1234/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            json=payload
        )
        
        if response.status_code != 200:
            raise Exception(f"LM Studio API returned status code {response.status_code}. Response: {response.text}")
            
        response_data = response.json()
        if 'choices' not in response_data or not response_data['choices']:
            raise Exception("Invalid response from LM Studio API")
            
        # Get the SQL query and clean it up
        sql_query = response_data["choices"][0]["message"]["content"].strip()
        
        # Remove any prefixes like "Output:", "Query:", etc.
        prefixes_to_remove = ["output:", "query:", "sql:", "result:"]
        for prefix in prefixes_to_remove:
            if sql_query.lower().startswith(prefix):
                sql_query = sql_query[len(prefix):].strip()
        
        # Clean up the SQL query
        sql_query = clean_sql_response(sql_query)
        
        # Basic SQL validation
        valid_commands = ('select', 'insert', 'create', 'update', 'delete', 'show', 'use', 'drop', 'describe', 'alter')
        if not any(sql_query.lower().startswith(cmd) for cmd in valid_commands):
            raise Exception("Generated query is not a valid SQL command")
            
        return sql_query
        
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to connect to LM Studio API: {str(e)}")
    except json.JSONDecodeError:
        raise Exception("Invalid JSON response from LM Studio API")
    except Exception as e:
        raise Exception(f"Error converting to SQL: {str(e)}")

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/databases', methods=['GET'])
def list_databases():
    """Endpoint to fetch list of databases"""
    databases = get_databases()
    return jsonify({"databases": databases})

@app.route('/create_database', methods=['POST'])
def create_database():
    """Endpoint to create a new database"""
    try:
        data = request.json
        db_name = data.get('database')
        use_now = data.get('use_now', False)
        
        if not db_name:
            return jsonify({"error": "Database name is required"}), 400
            
        # Validate database name
        if not db_name.isalnum() and not all(c.isalnum() or c == '_' for c in db_name):
            return jsonify({"error": "Database name can only contain letters, numbers, and underscores"}), 400
            
        connection = get_db_connection()
        if not connection:
            return jsonify({"error": "Could not connect to MySQL server"}), 500
            
        cursor = connection.cursor()
        
        try:
            # Create database
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
            connection.commit()
            
            response = {
                "message": f"Database '{db_name}' created successfully."
            }
            
            # If use_now is True, update the current database context
            if use_now:
                update_db_context(database=db_name)
                response["message"] += f" Now using database '{db_name}'."
            
            return jsonify(response)
            
        except mysql.connector.Error as err:
            return jsonify({"error": f"MySQL Error: {str(err)}"}), 400
        finally:
            cursor.close()
            connection.close()
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/query', methods=['POST'])
def query():
    try:
        user_input = request.json['message']
        selected_database = request.json.get('database')
        
        if not selected_database:
            return jsonify({
                "error": "No database selected. Please select a database first."
            }), 400
        
        # Update context with current database
        update_db_context(database=selected_database)
        
        # Convert natural language to SQL
        sql_query = convert_to_sql(user_input)
        
        # Execute SQL query
        connection = get_db_connection(selected_database)
        if not connection:
            return jsonify({"error": "Could not connect to MySQL database"}), 500
        
        cursor = connection.cursor(buffered=True)  # Use buffered cursor
        
        try:
            # Split multiple statements if present
            statements = [stmt.strip() for stmt in sql_query.split(';') if stmt.strip()]
            
            if not statements:
                return jsonify({"error": "No valid SQL statements found"}), 400
            
            # For CREATE TABLE, verify the table doesn't exist first
            if statements[0].lower().startswith('create table'):
                table_name = statements[0].lower().split('create table')[1].split('(')[0].strip()
                current_tables = get_current_tables(connection)
                if table_name in current_tables:
                    return jsonify({
                        "sql": sql_query,
                        "error": f"Table '{table_name}' already exists in the database."
                    }), 400
            
            # For DROP TABLE, use IF EXISTS to handle non-existent tables gracefully
            if statements[0].lower().startswith('drop table'):
                table_name = statements[0].lower().split('drop table')[1].strip().rstrip(';')
                # Modify the statement to include IF EXISTS
                statements[0] = f"DROP TABLE IF EXISTS {table_name}"
                sql_query = '; '.join(statements) + ';'
            
            # Execute each statement separately
            for statement in statements:
                cursor.execute(statement)
                connection.commit()
                
                # Fetch any results to prevent "Unread result found" error
                if cursor.with_rows:
                    cursor.fetchall()
            
            # Execute the last statement again to get its results
            cursor.execute(statements[-1])
            
            # Get the result from the last statement
            if cursor.with_rows:
                result = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                formatted_result = [dict(zip(columns, row)) for row in result]
                
                # Special handling for SHOW TABLES
                if statements[-1].lower().strip() == 'show tables':
                    # Get current tables from database
                    current_tables = get_current_tables(connection)
                    # Update context with actual table list
                    tables = {table: None for table in current_tables}
                    update_db_context(table_info=tables)
                    response = {
                        "sql": sql_query,
                        "output": [{"Tables_in_" + selected_database: table} for table in current_tables],
                        "message": f"Found {len(current_tables)} table(s) in the database.",
                        "type": "show_tables",
                        "loading": True
                    }
                # Special handling for DESCRIBE
                elif statements[-1].lower().startswith('describe'):
                    table_name = statements[-1].lower().split('describe')[1].strip()
                    # Update context with table structure
                    table_structure = get_table_structure(connection, table_name)
                    if table_structure:
                        update_db_context(table_info={table_name: table_structure})
                    response = {
                        "sql": sql_query,
                        "output": formatted_result,
                        "message": f"Table structure retrieved successfully.",
                        "type": "describe",
                        "loading": True
                    }
                else:
                    response = {
                        "sql": sql_query,
                        "output": formatted_result,
                        "message": f"Query returned {len(result)} row(s).",
                        "type": "select",
                        "loading": True
                    }
            else:
                # Determine query type and create appropriate message
                query_type = statements[-1].strip().split()[0].upper()
                if query_type == "CREATE":
                    if "TABLE" in statements[-1].upper():
                        response = {
                            "sql": sql_query,
                            "message": "Table created successfully.",
                            "type": "create",
                            "loading": True
                        }
                    elif "DATABASE" in statements[-1].upper():
                        response = {
                            "sql": sql_query,
                            "message": "Database created successfully.",
                            "type": "create",
                            "loading": True
                        }
                elif query_type == "UPDATE":
                    response = {
                        "sql": sql_query,
                        "message": "Data updated successfully.",
                        "type": "update",
                        "loading": True
                    }
                elif query_type == "DELETE":
                    response = {
                        "sql": sql_query,
                        "message": "Data deleted successfully.",
                        "type": "delete",
                        "loading": True
                    }
                elif query_type == "ALTER":
                    response = {
                        "sql": sql_query,
                        "message": "Table structure modified successfully.",
                        "type": "alter",
                        "loading": True
                    }
                elif query_type == "DROP":
                    if "TABLE" in statements[-1].upper():
                        # Check if the table was actually dropped
                        table_name = statements[-1].lower().split('drop table')[1].strip().rstrip(';')
                        if 'if exists' in statements[-1].lower():
                            current_tables = get_current_tables(connection)
                            if table_name in current_tables:
                                response = {
                                    "sql": sql_query,
                                    "message": "Table dropped successfully.",
                                    "type": "drop",
                                    "loading": True
                                }
                            else:
                                response = {
                                    "sql": sql_query,
                                    "message": f"Table '{table_name}' does not exist.",
                                    "type": "drop",
                                    "loading": True
                                }
                        else:
                            response = {
                                "sql": sql_query,
                                "message": "Table dropped successfully.",
                                "type": "drop",
                                "loading": True
                            }
                    elif "DATABASE" in statements[-1].upper():
                        response = {
                            "sql": sql_query,
                            "message": "Database dropped successfully.",
                            "type": "drop",
                            "loading": True
                        }
                else:
                    response = {
                        "sql": sql_query,
                        "message": "Query executed successfully.",
                        "type": "other",
                        "loading": True
                    }
                
                # Update context with query and result
                update_db_context(query=sql_query, result=response)
                
        except mysql.connector.Error as err:
            return jsonify({
                "sql": sql_query,
                "error": f"MySQL Error: {str(err)}"
            }), 400
        finally:
            cursor.close()
            connection.close()
            
        return jsonify(response)
        
    except Exception as e:
        return jsonify({
            "sql": sql_query if 'sql_query' in locals() else None,
            "error": str(e)
        }), 500

@app.route('/delete_databases', methods=['POST'])
def delete_databases():
    """Endpoint to delete multiple databases"""
    try:
        data = request.json
        databases = data.get('databases', [])
        
        if not databases:
            return jsonify({"error": "No databases selected for deletion"}), 400
            
        connection = get_db_connection()
        if not connection:
            return jsonify({"error": "Could not connect to MySQL server"}), 500
            
        cursor = connection.cursor()
        deleted_dbs = []
        errors = []
        
        try:
            for db_name in databases:
                try:
                    # Drop database
                    cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
                    deleted_dbs.append(db_name)
                except mysql.connector.Error as err:
                    errors.append(f"Error deleting database '{db_name}': {str(err)}")
            
            connection.commit()
            
            if errors:
                return jsonify({
                    "message": f"Successfully deleted {len(deleted_dbs)} database(s).",
                    "deleted": deleted_dbs,
                    "errors": errors
                })
            else:
                return jsonify({
                    "message": f"Successfully deleted {len(deleted_dbs)} database(s).",
                    "deleted": deleted_dbs
                })
            
        except mysql.connector.Error as err:
            return jsonify({"error": f"MySQL Error: {str(err)}"}), 400
        finally:
            cursor.close()
            connection.close()
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_table_details(connection, table_name):
    """Get detailed information about a table"""
    try:
        cursor = connection.cursor()
        
        # Get column information
        cursor.execute(f"DESCRIBE {table_name}")
        columns = cursor.fetchall()
        
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]
        
        # Get sample data (first 5 rows)
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
        sample_data = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]
        
        return {
            'columns': [{'field': col[0], 'type': col[1], 'null': col[2], 'key': col[3], 'default': col[4], 'extra': col[5]} for col in columns],
            'row_count': row_count,
            'sample_data': [dict(zip(column_names, row)) for row in sample_data]
        }
    except mysql.connector.Error as err:
        print(f"Error getting table details: {err}")
        return None
    finally:
        cursor.close()

@app.route('/visualize')
def visualize():
    """Serve the visualization page"""
    return send_from_directory('.', 'visualize.html')

@app.route('/api/relationships', methods=['GET'])
def get_relationships():
    """Get table relationships for visualization"""
    try:
        database = request.args.get('database')
        if not database:
            return jsonify({"error": "Database name is required"}), 400
            
        connection = get_db_connection(database)
        if not connection:
            return jsonify({"error": "Could not connect to MySQL database"}), 500
            
        relationships = get_table_relationships(connection, database)
        return jsonify({"relationships": relationships})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if 'connection' in locals():
            connection.close()

@app.route('/api/table_details', methods=['GET'])
def get_table_info():
    """Get detailed information about a specific table"""
    try:
        database = request.args.get('database')
        table = request.args.get('table')
        
        if not database or not table:
            return jsonify({"error": "Database and table names are required"}), 400
            
        connection = get_db_connection(database)
        if not connection:
            return jsonify({"error": "Could not connect to MySQL database"}), 500
            
        details = get_table_details(connection, table)
        if details is None:
            return jsonify({"error": f"Could not get details for table {table}"}), 404
            
        return jsonify(details)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if 'connection' in locals():
            connection.close()

@app.route('/select_database', methods=['POST'])
def select_database():
    """Endpoint to select a database and analyze its structure"""
    try:
        data = request.json
        database = data.get('database')
        
        if not database:
            return jsonify({"error": "Database name is required"}), 400
        
        # Update database context
        update_db_context(database=database)
        
        # Get database information
        db_info = get_database_info(database)
        if not db_info:
            return jsonify({"error": "Could not analyze database structure"}), 500
        
        return jsonify({
            "message": f"Database '{database}' selected and analyzed successfully.",
            "status": "analyzing",
            "tables": list(db_info['tables'].keys()),
            "last_updated": db_info['last_updated']
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True) 