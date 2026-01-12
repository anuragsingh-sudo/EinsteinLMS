# app.py
from flask import Flask, render_template, request, jsonify, g
import sqlite3
import uuid
import datetime

app = Flask(__name__)
DB_FILE = 'lms_database.db'

# --- Database Connection Management ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_FILE)
        db.row_factory = sqlite3.Row # Access columns by name
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """Creates the database tables automatically on first run."""
    with app.app_context():
        db = get_db()
        # Users Table
        db.execute('''CREATE TABLE IF NOT EXISTS Users 
                     (id TEXT PRIMARY KEY, name TEXT, email TEXT, password TEXT, role TEXT, timestamp TEXT)''')
        # Batches Table
        db.execute('''CREATE TABLE IF NOT EXISTS Batches 
                     (code TEXT PRIMARY KEY, name TEXT, trainer_id TEXT, start_date TEXT, end_date TEXT, max_capacity INTEGER)''')
        # Trainees Table
        db.execute('''CREATE TABLE IF NOT EXISTS Trainees 
                     (id TEXT PRIMARY KEY, batch_code TEXT, name TEXT, mobile TEXT, email TEXT)''')
        # Attendance Table
        db.execute('''CREATE TABLE IF NOT EXISTS Attendance 
                     (id TEXT PRIMARY KEY, batch_code TEXT, trainee_id TEXT, date TEXT, status TEXT)''')
        
        # Create Default Owner Account (Email: admin@lms.com / Pass: 12345)
        try:
            db.execute("INSERT INTO Users (id, name, email, password, role) VALUES (?, ?, ?, ?, ?)",
                       ('USR-OWNER', 'Admin', 'admin@lms.com', '12345', 'Owner'))
            db.commit()
        except sqlite3.IntegrityError:
            pass # Already exists

# --- Page Routes ---
@app.route('/')
def index():
    # Passes 'mode' and 'email' to HTML just like GAS did
    mode = request.args.get('mode', 'login')
    email = request.args.get('email', '')
    return render_template('Index.html', mode=mode, inviteEmail=email)

# --- API Routes (Replacing google.script.run) ---

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    db = get_db()
    cur = db.execute("SELECT * FROM Users WHERE lower(email) = ?", (data['email'].lower(),))
    user = cur.fetchone()
    
    if user:
        if user['password'] == 'PENDING_SETUP':
            return jsonify({'status': 'error', 'message': 'Account pending setup.'})
        if str(user['password']) == str(data['password']):
            return jsonify({'status': 'success', 'user': {'id': user['id'], 'name': user['name'], 'role': user['role']}})
    
    return jsonify({'status': 'error', 'message': 'Invalid Credentials'})

@app.route('/api/get_batches', methods=['POST'])
def get_batches():
    data = request.json
    user_id = data.get('userId')
    role = data.get('role')
    
    db = get_db()
    if role == 'Owner':
        cur = db.execute("SELECT * FROM Batches")
    else:
        cur = db.execute("SELECT * FROM Batches WHERE trainer_id = ?", (user_id,))
    
    rows = cur.fetchall()
    # Format dates for frontend
    result = [{'code': r['code'], 'name': r['name'], 'start': r['start_date']} for r in rows]
    return jsonify(result)

@app.route('/api/get_trainers', methods=['GET'])
def get_trainers():
    db = get_db()
    cur = db.execute("SELECT id, name FROM Users WHERE role = 'Trainer'")
    rows = cur.fetchall()
    return jsonify([{'id': r['id'], 'name': r['name']} for r in rows])

@app.route('/api/create_batch', methods=['POST'])
def create_batch():
    data = request.json
    db = get_db()
    
    # 1. Insert Batch
    db.execute("INSERT INTO Batches (code, name, trainer_id, start_date, end_date, max_capacity) VALUES (?,?,?,?,?,?)",
               (data['batch_code'], data['batch_name'], data['trainer_id'], data['start_date'], data['end_date'], data['max_capacity']))
    
    # 2. Insert Trainees
    if data.get('trainees'):
        for t in data['trainees']:
            t_id = 'TR-' + str(uuid.uuid4())[:8]
            db.execute("INSERT INTO Trainees (id, batch_code, name, mobile, email) VALUES (?,?,?,?,?)",
                       (t_id, data['batch_code'], t['name'], t['mobile'], ''))
    
    db.commit()
    return jsonify({'status': 'success'})

@app.route('/api/get_trainees', methods=['POST'])
def get_trainees():
    batch_code = request.json.get('batchCode')
    db = get_db()
    cur = db.execute("SELECT * FROM Trainees WHERE batch_code = ?", (batch_code,))
    rows = cur.fetchall()
    return jsonify([{'id': r['id'], 'name': r['name'], 'mobile': r['mobile']} for r in rows])

@app.route('/api/save_attendance', methods=['POST'])
def save_attendance():
    data = request.json
    db = get_db()
    for rec in data['records']:
        att_id = str(uuid.uuid4())
        db.execute("INSERT INTO Attendance (id, batch_code, trainee_id, date, status) VALUES (?,?,?,?,?)",
                   (att_id, data['batch_code'], rec['trainee_id'], data['date'], rec['status']))
    db.commit()
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    init_db()
    print("----------------------------------------------------------------")
    print(" SERVER STARTED.")
    print(" 1. Open Browser to: http://127.0.0.1:5000")
    print(" 2. Login with: admin@lms.com  |  Password: 12345")
    print("----------------------------------------------------------------")
    app.run(debug=True, port=5000)

