# Natural Language SQL Assistant

A web-based chatbot that converts natural language to SQL queries and executes them on a MySQL database using LM Studio for natural language processing.

## Features

- Convert natural language to SQL queries using Mistral-7B model
- Execute SQL queries on MySQL database
- Modern and user-friendly web interface
- Real-time query execution and results display
- Error handling and feedback

## Prerequisites

- Python 3.8 or higher
- MySQL Server
- LM Studio with Mistral-7B-Instruct-v0.2 model loaded

## Setup

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure MySQL:
   - Make sure MySQL server is running
   - Default configuration in app.py:
     - Host: localhost
     - User: root
     - Password: password

3. Start LM Studio:
   - Load the Mistral-7B-Instruct-v0.2 model
   - Enable API Server (http://127.0.0.1:1225)

4. Start the Flask backend:
   ```bash
   python app.py
   ```

5. Open `index.html` in your web browser

## Usage

1. Type your natural language query in the input box
2. Press Enter or click Send
3. The system will:
   - Convert your request to SQL
   - Execute the query
   - Display the results

Example queries:
- "create database test"
- "create table users with columns id, name, and email"
- "insert into users values (1, 'John Doe', 'john@example.com')"
- "select all users from the database"
- "show me all tables in the database"

## Security Notes

- This is a development setup. For production:
  - Use environment variables for sensitive data
  - Implement proper authentication
  - Add input validation
  - Use HTTPS
  - Implement rate limiting

## Troubleshooting

1. If you can't connect to MySQL:
   - Check if MySQL server is running
   - Verify credentials in app.py
   - Ensure MySQL user has proper permissions

2. If LM Studio is not responding:
   - Verify LM Studio is running
   - Check if the model is loaded
   - Confirm API server is enabled on port 1234

3. If the web interface doesn't work:
   - Check if Flask server is running
   - Open browser console for errors
   - Verify CORS settings if accessing from different domain 