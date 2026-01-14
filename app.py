import os
import uuid
import datetime
import json
from flask import Flask, render_template, request, jsonify

# Import Google Cloud Libraries
try:
    from google.cloud import firestore
    from google.cloud import secretmanager
    from google.oauth2 import service_account
except ImportError:
    print("CRITICAL ERROR: Google Cloud libraries not found.")
    print("Run: pip install google-cloud-firestore google-cloud-secret-manager")
    exit(1)

app = Flask(__name__)

SECRET_RESOURCE_ID = "projects/648176215467/secrets/vega-service-key/versions/1"

def get_db_connection():
    """
    Attempts to fetch credentials from Secret Manager and connect to Firestore.
    """
    try:
    
        sm_client = secretmanager.SecretManagerServiceClient()
        
        print(f"🔐 Fetching credentials from Secret Manager...")
        response = sm_client.access_secret_version(request={"name": SECRET_RESOURCE_ID})
        
        # 2. Parse the Secret Payload (JSON Key)
        secret_payload = response.payload.data.decode("UTF-8")
        service_account_info = json.loads(secret_payload)
        
        # 3. Create Credentials object from the JSON info
        creds = service_account.Credentials.from_service_account_info(service_account_info)
        
        # 4. Connect to Firestore using these credentials
        db_client = firestore.Client(credentials=creds)
        print("✅ Successfully connected to Firestore using Secret Key.")
        return db_client

    except Exception as e:
        print(f"⚠️ Secret Manager Connection Failed: {e}")
        print("Falling back to Default Credentials (Cloud Run default)...")
        try:
            # Fallback for Cloud Run if Secret Manager fails or permissions missing
            return firestore.Client()
        except Exception as e2:
            print(f"❌ Critical DB Error: {e2}")
            return None

# Initialize DB
db = get_db_connection()

# --- Firestore Helpers ---
def get_all(collection, filters=None):
    if not db: return []
    ref = db.collection(collection)
    if filters:
        for key, op, val in filters:
            ref = ref.where(filter=firestore.FieldFilter(key, op, val))
    docs = ref.stream()
    return [{**doc.to_dict(), 'id': doc.id} for doc in docs]

def get_doc(collection, doc_id):
    if not db: return None
    doc = db.collection(collection).document(str(doc_id)).get()
    if doc.exists:
        data = doc.to_dict()
        data['id'] = doc.id
        return data
    return None

def add_doc(collection, doc_id, data):
    if not db: return
    db.collection(collection).document(str(doc_id)).set(data)

# ==========================================
# 2. ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template('Index.html', mode=request.args.get('mode', 'login'), inviteEmail=request.args.get('email', ''))

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    users = get_all('Users', [('email', '==', data['email'])])
    
    if users:
        u = users[0]
        if u.get('password') == 'PENDING_SETUP': 
            return jsonify({'status': 'error', 'message': 'Account pending setup.'})
        if str(u.get('password')) == str(data['password']): 
            return jsonify({'status': 'success', 'user': {'id': u['id'], 'name': u['name'], 'role': u['role']}})
            
    return jsonify({'status': 'error', 'message': 'Invalid Credentials'})

@app.route('/api/get_batches', methods=['POST'])
def get_batches():
    d = request.json
    if d.get('role') == 'Owner':
        batches = get_all('Batches')
    else:
        batches = get_all('Batches', [('trainer_id', '==', d.get('userId'))])
    return jsonify(batches)

@app.route('/api/create_batch', methods=['POST'])
def create_batch():
    d = request.json
    add_doc('Batches', d['batch_code'], {
        'code': d['batch_code'], 'name': d['batch_name'], 
        'trainer_id': d['trainer_id'], 'start_date': d['start_date'], 
        'end_date': d['end_date'], 'max_capacity': d['max_capacity']
    })
    if d.get('trainees'):
        for t in d['trainees']:
            tid = 'TR-' + str(uuid.uuid4())[:8]
            add_doc('Trainees', tid, {'id': tid, 'batch_code': d['batch_code'], 'name': t['name'], 'mobile': t['mobile'], 'email': ''})
    return jsonify({'status': 'success'})

@app.route('/api/get_trainers', methods=['GET'])
def get_trainers():
    return jsonify([{'id': t['id'], 'name': t['name']} for t in get_all('Users', [('role', '==', 'Trainer')])])

@app.route('/api/invite_trainer', methods=['POST'])
def invite_trainer():
    d = request.json
    existing = get_all('Users', [('email', '==', d['email'])])
    if existing: return jsonify({'status': 'error', 'message': 'Email exists'})
    
    uid = 'USR-' + str(uuid.uuid4())[:8]
    add_doc('Users', uid, {'id': uid, 'name': d['name'], 'email': d['email'], 'password': '12345', 'role': 'Trainer'})
    return jsonify({'status': 'success'})

@app.route('/api/get_trainees', methods=['POST'])
def get_trainees():
    return jsonify(get_all('Trainees', [('batch_code', '==', request.json.get('batchCode'))]))

@app.route('/api/add_trainee', methods=['POST'])
def add_trainee():
    d = request.json
    batch = get_doc('Batches', d['batchCode'])
    if not batch: return jsonify({'status': 'error'})
    
    tid = 'TR-' + str(uuid.uuid4())[:8]
    add_doc('Trainees', tid, {'id': tid, 'batch_code': d['batchCode'], 'name': d['name'], 'mobile': d['mobile'], 'email': d['email']})
    return jsonify({'status': 'success'})

@app.route('/api/save_attendance', methods=['POST'])
def save_attendance():
    d = request.json
    for r in d['records']:
        aid = str(uuid.uuid4())
        add_doc('Attendance', aid, {'id': aid, 'batch_code': d['batch_code'], 'trainee_id': r['trainee_id'], 'date': d['date'], 'status': r['status']})
    return jsonify({'status': 'success'})

@app.route('/api/get_trainee_details', methods=['POST'])
def get_details():
    tid = request.json.get('id')
    t = get_doc('Trainees', tid)
    if not t: return jsonify({'status': 'error', 'message': 'Not found'})
    
    all_att = get_all('Attendance', [('trainee_id', '==', tid)])
    total = len(all_att)
    present = len([x for x in all_att if x['status'] == 'P'])
    pct = round((present/total*100)) if total else 0
    
    modules = {
        '1': {'score': 'Pending', 'attempts': 0},
        '2': {'score': 'Pending', 'attempts': 0},
        '3': {'score': 'Pending', 'attempts': 0}
    }
    
    results = get_all('Results', [('trainee_id', '==', tid)])
    for r in results:
        mn = str(r['module_num'])
        if mn in modules:
            modules[mn]['score'] = r.get('score', 'Submitted')
            modules[mn]['attempts'] += 1
            
    curriculum = [
        {'name': 'Semester 1', 'modules': [1, 2]},
        {'name': 'Semester 2', 'modules': [3]}
    ]

    return jsonify({
        'status': 'success',
        'info': t,
        'stats': {'percentage': pct},
        'modules': modules,
        'curriculum': curriculum
    })

@app.route('/api/get_test_setup', methods=['POST'])
def get_test(): return jsonify({'questions': [{'question': 'Describe the core concepts.'}]})

@app.route('/api/save_assessment', methods=['POST'])
def save_asm():
    d = request.json
    rid = str(uuid.uuid4())
    add_doc('Results', rid, {
        'id': rid, 'trainee_id': d['tId'], 'trainee_name': d['tName'], 
        'module_num': d['mNum'], 'video_link': 'mock_vid', 'audio_link': 'mock_aud', 
        'score': 'Pending', 'timestamp': str(datetime.datetime.now())
    })
    return jsonify({'status': 'success'})

@app.route('/_init_db')
def init_db():
    add_doc('Users', 'USR-OWNER', {'id': 'USR-OWNER', 'name': 'Admin', 'email': 'admin@lms.com', 'password': '12345', 'role': 'Owner'})
    return "DB Initialized"

if __name__ == '__main__':
    print(f"Connecting to Secret Manager: {SECRET_RESOURCE_ID}")
    app.run(debug=True, port=5000)

