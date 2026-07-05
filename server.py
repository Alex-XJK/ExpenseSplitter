from flask import Flask, render_template, jsonify, request, abort
import sqlite3
import json
import os

app = Flask(__name__)
app.config['DATABASE'] = os.environ.get('EXPENSE_SPLITTER_DATABASE', 'database.db')
CONFIG_FILE = os.environ.get('EXPENSE_SPLITTER_CONFIG', 'config.json')


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Warning: {CONFIG_FILE} not found. Please create it from config.json.example")
        return {}

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing {CONFIG_FILE}: {e}")
        return {}
    except Exception as e:
        print(f"Error loading {CONFIG_FILE}: {e}")
        return {}


def normalize_currencies(config):
    raw_currencies = config.get('currencies', {})
    currencies = {}

    for code, details in raw_currencies.items():
        code = code.upper()
        if isinstance(details, (int, float)):
            details = {'rate_to_usd': details}

        try:
            rate_to_usd = float(details.get('rate_to_usd', 1))
        except (TypeError, ValueError):
            print(f"Warning: Invalid rate_to_usd for {code}; skipping currency")
            continue

        if rate_to_usd <= 0:
            print(f"Warning: rate_to_usd must be positive for {code}; skipping currency")
            continue

        currencies[code] = {
            'code': code,
            'name': details.get('name', code),
            'symbol': details.get('symbol', code),
            'rate_to_usd': rate_to_usd
        }

    currencies.setdefault('USD', {
        'code': 'USD',
        'name': 'US Dollar',
        'symbol': '$',
        'rate_to_usd': 1.0
    })

    return currencies


CONFIG = load_config()
SESSIONS = CONFIG.get('sessions', {})
CURRENCIES = normalize_currencies(CONFIG)


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
                original_amount REAL,
                original_currency TEXT DEFAULT 'USD',
                exchange_rate_to_usd REAL DEFAULT 1,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        columns = {
            column['name']
            for column in db.execute('PRAGMA table_info(expenses)').fetchall()
        }
        migrations = {
            'original_amount': "ALTER TABLE expenses ADD COLUMN original_amount REAL",
            'original_currency': "ALTER TABLE expenses ADD COLUMN original_currency TEXT DEFAULT 'USD'",
            'exchange_rate_to_usd': "ALTER TABLE expenses ADD COLUMN exchange_rate_to_usd REAL DEFAULT 1",
            'created_by': "ALTER TABLE expenses ADD COLUMN created_by TEXT"
        }

        for column, statement in migrations.items():
            if column not in columns:
                db.execute(statement)

        db.execute('''
            UPDATE expenses
            SET original_amount = amount
            WHERE original_amount IS NULL
        ''')
        db.commit()
        db.close()


def get_requested_username():
    data = request.get_json(silent=True) or {}
    return (
        request.args.get('username')
        or data.get('username')
        or data.get('created_by')
        or request.headers.get('X-Expense-User')
    )


def is_session_user(session_id, username):
    return username in SESSIONS.get(session_id, {}).get('users', [])



def get_public_sessions():
    public_sessions = []
    for session in SESSIONS.values():
        description = session.get('description') or 'Private expense session'
        public_sessions.append({'description': description})
    return public_sessions


@app.route('/')
def index():
    status_code = 200 if SESSIONS else 503
    return render_template(
        'home.html',
        sessions=get_public_sessions(),
        has_sessions=bool(SESSIONS)
    ), status_code


@app.route('/session/<session_id>/user/<username>')
def session_page(session_id, username):
    if session_id not in SESSIONS:
        abort(404, description="Invalid session ID")

    if username not in SESSIONS[session_id]['users']:
        abort(403, description="User not authorized for this session")

    users = SESSIONS[session_id]['users']
    default_paid_by = 'B' if len(users) > 1 and username == users[1] else 'A'

    return render_template(
        'expense_splitter.html',
        default_paid_by=default_paid_by
    )


@app.route('/api/session/<session_id>/info')
def get_session_info(session_id):
    if session_id not in SESSIONS:
        return jsonify({'error': 'Invalid session ID'}), 404

    return jsonify({
        'session_id': session_id,
        'person_a': SESSIONS[session_id]['person_a'],
        'person_b': SESSIONS[session_id]['person_b'],
        'currencies': CURRENCIES
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

    data = request.json or {}

    required = ['description', 'datetime', 'paid_by', 'split_mode']
    if not all(field in data for field in required):
        return jsonify({'error': 'Missing required fields'}), 400

    amount_input = data.get('original_amount', data.get('amount'))
    if amount_input is None:
        return jsonify({'error': 'Missing required amount'}), 400

    try:
        original_amount = float(amount_input)
    except (TypeError, ValueError):
        return jsonify({'error': 'Amount must be a number'}), 400

    if original_amount < 0:
        return jsonify({'error': 'Amount must be non-negative'}), 400

    original_currency = str(data.get('original_currency') or 'USD').upper()
    currency = CURRENCIES.get(original_currency)
    if not currency:
        return jsonify({'error': f'Unsupported currency: {original_currency}'}), 400

    created_by = data.get('created_by')
    if created_by and not is_session_user(session_id, created_by):
        return jsonify({'error': 'Creator is not authorized for this session'}), 403

    amount_usd = round(original_amount * currency['rate_to_usd'], 2)

    db = get_db()
    cursor = db.execute(
        '''INSERT INTO expenses (session_id, description, amount, datetime,
           paid_by, split_mode, ratio_a, ratio_b, original_amount, original_currency,
           exchange_rate_to_usd, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (session_id, data['description'], amount_usd, data['datetime'],
         data['paid_by'], data['split_mode'],
         data.get('ratio_a'), data.get('ratio_b'), original_amount,
         original_currency, currency['rate_to_usd'], created_by)
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

    username = get_requested_username()
    if not is_session_user(session_id, username):
        return jsonify({'error': 'User not authorized for this session'}), 403

    db = get_db()
    expense = db.execute(
        'SELECT created_by FROM expenses WHERE id = ? AND session_id = ?',
        (expense_id, session_id)
    ).fetchone()

    if not expense:
        db.close()
        return jsonify({'error': 'Expense not found'}), 404

    if expense['created_by'] and expense['created_by'] != username:
        db.close()
        return jsonify({'error': 'Only the creator can delete this expense'}), 403

    db.execute('DELETE FROM expenses WHERE id = ? AND session_id = ?',
               (expense_id, session_id))
    db.commit()
    db.close()

    return jsonify({'success': True})


init_db()

if __name__ == '__main__':
    if not SESSIONS:
        print("ERROR: No sessions configured!")
        print("Please create config.json from config.json.example")
        exit(1)

    app.run(host='0.0.0.0', port=5000, debug=True)
