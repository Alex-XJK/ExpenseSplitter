from flask import Flask, render_template, jsonify, request, abort
import sqlite3
import json
from datetime import datetime
import os

app = Flask(__name__)
app.config['DATABASE'] = 'database.db'

# Load session configuration from config.json
def load_sessions():
    config_file = 'config.json'
    if not os.path.exists(config_file):
        print(f"Warning: {config_file} not found. Please create it from config.json.example")
        return {}
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get('sessions', {})
    except json.JSONDecodeError as e:
        print(f"Error parsing {config_file}: {e}")
        return {}
    except Exception as e:
        print(f"Error loading {config_file}: {e}")
        return {}

SESSIONS = load_sessions()

def get_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                datetime TEXT NOT NULL,
                paid_by TEXT NOT NULL,
                split_mode TEXT NOT NULL,
                ratio_a REAL,
                ratio_b REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()
        db.close()

@app.route('/')
def index():
    if not SESSIONS:
        return '''
        <html>
        <head><title>Alex's Expense Splitter - Configuration Required</title></head>
        <body>
            <h1>Alex's Expense Splitter</h1>
            <p style="color: red;">No sessions configured. Please create config.json from config.json.example</p>
        </body>
        </html>
        '''
    
    session_links = ''.join([
        f'<li>{sid}</li>'
        for sid, session in SESSIONS.items()
        if session.get('users') and len(session['users']) > 0
    ])
    
    return f'''
    <html>
    <head><title>Alex's Expense Splitter</title></head>
    <body>
        <h1>Alex's Expense Splitter</h1>
        <p>Access your session at: /session/{{session_id}}/user/{{username}}</p>
        <p>Available sessions:</p>
        <ul>
            {session_links}
        </ul>
    </body>
    </html>
    '''

@app.route('/session/<session_id>/user/<username>')
def session_page(session_id, username):
    if session_id not in SESSIONS:
        abort(404, description="Invalid session ID")
    
    if username not in SESSIONS[session_id]['users']:
        abort(403, description="User not authorized for this session")
    
    return render_template('expense_splitter.html')

@app.route('/api/session/<session_id>/info')
def get_session_info(session_id):
    if session_id not in SESSIONS:
        return jsonify({'error': 'Invalid session ID'}), 404
    
    return jsonify({
        'session_id': session_id,
        'person_a': SESSIONS[session_id]['person_a'],
        'person_b': SESSIONS[session_id]['person_b']
    })

@app.route('/api/session/<session_id>/expenses', methods=['GET'])
def get_expenses(session_id):
    if session_id not in SESSIONS:
        return jsonify({'error': 'Invalid session ID'}), 404
    
    db = get_db()
    expenses = db.execute(
        'SELECT * FROM expenses WHERE session_id = ? ORDER BY datetime DESC',
        (session_id,)
    ).fetchall()
    db.close()
    
    return jsonify([dict(expense) for expense in expenses])

@app.route('/api/session/<session_id>/expenses', methods=['POST'])
def add_expense(session_id):
    if session_id not in SESSIONS:
        return jsonify({'error': 'Invalid session ID'}), 404
    
    data = request.json
    
    # Validate required fields
    required = ['description', 'amount', 'datetime', 'paid_by', 'split_mode']
    if not all(field in data for field in required):
        return jsonify({'error': 'Missing required fields'}), 400
    
    db = get_db()
    cursor = db.execute(
        '''INSERT INTO expenses (session_id, description, amount, datetime, 
           paid_by, split_mode, ratio_a, ratio_b)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (session_id, data['description'], data['amount'], data['datetime'],
         data['paid_by'], data['split_mode'], 
         data.get('ratio_a'), data.get('ratio_b'))
    )
    db.commit()
    
    expense_id = cursor.lastrowid
    expense = db.execute('SELECT * FROM expenses WHERE id = ?', (expense_id,)).fetchone()
    db.close()
    
    return jsonify(dict(expense)), 201

@app.route('/api/session/<session_id>/expenses/<int:expense_id>', methods=['DELETE'])
def delete_expense(session_id, expense_id):
    if session_id not in SESSIONS:
        return jsonify({'error': 'Invalid session ID'}), 404
    
    db = get_db()
    db.execute('DELETE FROM expenses WHERE id = ? AND session_id = ?', 
               (expense_id, session_id))
    db.commit()
    db.close()
    
    return jsonify({'success': True})

if __name__ == '__main__':
    if not SESSIONS:
        print("ERROR: No sessions configured!")
        print("Please create config.json from config.json.example")
        exit(1)
    
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)