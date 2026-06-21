import os
import re
import json
import secrets
import datetime
import requests
from flask import Flask, request, jsonify, Response
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db as fb_db

app = Flask(__name__)

# =========================================================================
# ফায়ারবেজ এডমিন কনফিগারেশন 
# =========================================================================
FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "https://mino-sms-2c740-default-rtdb.firebaseio.com/")

CRED_DICT = {
  "type": "service_account",
  "project_id": "mino-sms-2c740",
  "private_key_id": "a85ea572c42697fea434427351256de4ad047c44",
  "private_key": os.environ.get("FIREBASE_PRIVATE_KEY"), 
  "client_email": "firebase-adminsdk-fbsvc@mino-sms-2c740.iam.gserviceaccount.com",
  "client_id": "109781975935982579945",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40mino-sms-2c740.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

# ফায়ারবেজ অ্যাপ ইনিশিয়েলাইজেশন
if not firebase_admin._apps and CRED_DICT.get("private_key"):
    CRED_DICT["private_key"] = CRED_DICT["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(CRED_DICT)
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })
elif not firebase_admin._apps:
    print("Warning: Firebase Credentials could not be loaded because FIREBASE_PRIVATE_KEY is missing.")

# =========================================================================
# এডমিন ক্রেডেনশিয়াল এবং অথেনটিকেশন হেল্পার 
# =========================================================================
ADMIN_USER = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_STATIC_TOKEN = f"admin_tkn_{ADMIN_PASS}"

def verify_admin():
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        if token == ADMIN_STATIC_TOKEN:
            return True
    return False

# মেনটেইনেন্স মোড চেক করার ফাংশন
def is_maintenance():
    try:
        val = fb_db.reference('/settings/maintenance_mode').get()
        return bool(val)
    except Exception:
        return False

# =========================================================================
# বিফোর রিকোয়েস্ট (CORS এবং মেনটেইনেন্স মোড)
# =========================================================================
@app.before_request
def handle_pre_requests():
    if request.method == 'OPTIONS':
        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-MINO-API-KEY,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        return response

    if not request.path.startswith('/admin') and not request.path.startswith('/api/v1/admin'):
        if is_maintenance():
            if request.path.startswith('/api/v1/'):
                return jsonify({'status': 'error', 'message': 'System is under maintenance'}), 503
            
            maintenance_html = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
              <meta charset="UTF-8">
              <meta name="viewport" content="width=device-width, initial-scale=1.0">
              <title>Under Maintenance</title>
              <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-slate-50 flex items-center justify-center h-screen font-sans">
              <div class="text-center p-8 bg-white rounded-3xl border border-slate-200 shadow-sm max-w-md mx-4 space-y-4">
                <div class="h-16 w-16 bg-amber-50 text-amber-600 rounded-full flex items-center justify-center text-3xl mx-auto shadow-sm">🛠️</div>
                <h1 class="text-xl font-black text-slate-800">ওয়েবসাইট সাময়িকভাবে বন্ধ আছে</h1>
                <p class="text-xs text-slate-500 leading-relaxed font-semibold">আমাদের সিস্টেম বর্তমানে আপগ্রেড বা উন্নয়নমূলক কাজের জন্য সাময়িকভাবে বন্ধ আছে। খুব শীঘ্রই আমরা পুনরায় ফিরে আসছি।</p>
                <div class="border-t border-slate-100 pt-4">
                  <p class="text-[10px] uppercase tracking-widest font-bold text-[#0088CC]">MINO SMS PANEL</p>
                </div>
              </div>
            </body>
            </html>
            """
            return Response(maintenance_html, mimetype='text/html'), 503

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-MINO-API-KEY,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# =========================================================================
# ডেটাবেজ হ্যান্ডলারস 
# =========================================================================
MEMORY_DB = None

COUNTRY_PREFIXES = {
    "224": "Guinea", "225": "Ivory Coast", "236": "Central African Republic",
    "221": "Senegal", "223": "Mali", "226": "Burkina Faso", "227": "Niger",
    "228": "Togo", "229": "Benin", "237": "Cameroon", "241": "Gabon",
    "242": "Congo", "243": "DR Congo", "235": "Chad", "240": "Equatorial Guinea",
    "231": "Liberia", "232": "Sierra Leone", "233": "Ghana", "234": "Nigeria",
    "250": "Rwanda", "254": "Kenya", "255": "Tanzania", "256": "Uganda",
    "257": "Burundi", "261": "Madagascar", "269": "Comoros"
}

def get_country_from_range(range_str):
    if not range_str:
        return "Unknown"
    clean_range = "".join(filter(str.isdigit, str(range_str)))
    for prefix, country in COUNTRY_PREFIXES.items():
        if clean_range.startswith(prefix):
            return country
    return "Guinea"

def firebase_to_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        lst = []
        for k, v in data.items():
            if isinstance(v, dict):
                v['id'] = k  
                lst.append(v)
            else:
                lst.append(v)
        return lst
    return []

def load_db():
    global MEMORY_DB
    try:
        ref = fb_db.reference('/')
        db_data = ref.get()
        
        if not db_data or not isinstance(db_data, dict):
            db_data = {
                "users": {},
                "allocated_numbers": [],
                "otp_logs": [],
                "live_console": []
            }
        
        if "users" not in db_data or not isinstance(db_data["users"], dict): 
            db_data["users"] = {}
            
        db_data["allocated_numbers"] = firebase_to_list(db_data.get("allocated_numbers"))
        db_data["otp_logs"] = firebase_to_list(db_data.get("otp_logs"))
        db_data["live_console"] = firebase_to_list(db_data.get("live_console"))
        
        MEMORY_DB = db_data
        return MEMORY_DB
    except Exception as e:
        print("Firebase Admin Load Error:", e)
        if MEMORY_DB is not None:
            return MEMORY_DB
        return {
            "users": {},
            "allocated_numbers": [],
            "otp_logs": [],
            "live_console": []
        }

def parse_iso_datetime(dt_str):
    if not dt_str:
        return datetime.datetime.now(datetime.timezone.utc)
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    try:
        return datetime.datetime.fromisoformat(dt_str)
    except Exception:
        try:
            return datetime.datetime.strptime(dt_str.split('.')[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc)

STEX_API_KEY = os.environ.get("STEX_API_KEY", "MWF1Z0QG1DJ")
STEX_BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api"

def mask_number(number):
    if not number:
        return ''
    length = len(number)
    if length < 8:
        return number
    return f"{number[:6]}****{number[length-3:]}"

# অথেনটিকেশন মিডলওয়্যার (অ্যাপ্রুভড ইউজার অনলি)
def get_current_user(db):
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        user = db["users"].get(token)
        if user and user.get('status', 'pending') == 'approved':
            return user

    api_key = request.headers.get('X-MINO-API-KEY') or request.args.get('api_key')
    if api_key:
        for u in db["users"].values():
            if u.get('api_key') and u['api_key'] == api_key and u.get('status', 'pending') == 'approved':
                return u
    return None

# =========================================================================
# ইউজার এপিআই সমূহ 
# =========================================================================
@app.route('/api/v1/auth/register', methods=['POST'])
def register():
    try:
        data = request.json or {}
        email = data.get('email')
        password = data.get('password')
        name = data.get('name', '').strip()

        if not email or not password:
            return jsonify({'status': 'error', 'message': 'Email and password are required'}), 400

        if not name:
            name = email.split('@')[0]

        db = load_db()
        for u in db["users"].values():
            if u['email'] == email:
                return jsonify({'status': 'error', 'message': 'Email already registered'}), 400

        uid = "usr_" + secrets.token_hex(8)

        user_data = {
            'uid': uid,
            'name': name,
            'email': email,
            'password': password,
            'api_key': '',
            'balance': 0.00,
            'otp_rate': 0.40,
            'wallet_address': '', 
            'id_code': f"MINO-{secrets.randbelow(9000) + 1000}",
            'status': 'pending', 
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        fb_db.reference(f'/users/{uid}').set(user_data)
        return jsonify({'status': 'success', 'message': 'Registration pending admin approval', 'token': uid, 'user': user_data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/v1/auth/login', methods=['POST'])
def login():
    try:
        data = request.json or {}
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'status': 'error', 'message': 'Email and password are required'}), 400

        db = load_db()
        for uid, u in db["users"].items():
            if u['email'] == email and u['password'] == password:
                status = u.get('status', 'pending')
                if status == 'pending':
                    return jsonify({'status': 'error', 'message': 'আপনার অ্যাকাউন্টটি অনুমোদনের জন্য অপেক্ষমান। অনুগ্রহ করে অ্যাডমিনের সাথে যোগাযোগ করুন।'}), 403
                if status == 'banned':
                    return jsonify({'status': 'error', 'message': 'আপনার অ্যাকাউন্টটি ব্যান করা হয়েছে।'}), 403
                
                return jsonify({'status': 'success', 'token': uid, 'user': u})

        return jsonify({'status': 'error', 'message': 'ইমেইল বা পাসওয়ার্ড ভুল।'}), 401
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/auth/me', methods=['GET'])
def get_me():
    try:
        db = load_db()
        u = get_current_user(db)
        if not u:
            return jsonify({'status': 'error', 'message': 'Unauthorized or Pending Approval'}), 401
        
        # গ্লোবাল অ্যানাউন্সমেন্ট ব্যানার ফেচ
        announcement = fb_db.reference('/settings/announcement').get() or ''
        return jsonify({'status': 'success', 'user': u, 'announcement': announcement})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/user/generate-key', methods=['POST'])
def generate_api_key():
    try:
        db = load_db()
        user = get_current_user(db)
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        
        user_id = user['uid']
        if not db["users"][user_id].get('api_key'):
            unique_key = 'mino_live_' + secrets.token_hex(16)
            fb_db.reference(f'/users/{user_id}/api_key').set(unique_key)
            return jsonify({'status': 'success', 'message': 'API Key generated', 'api_key': unique_key})
        else:
            return jsonify({'status': 'success', 'message': 'API Key already exists', 'api_key': db["users"][user_id]['api_key']})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/user/update-wallet', methods=['POST'])
def update_wallet():
    try:
        db = load_db()
        user = get_current_user(db)
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        
        data = request.json or {}
        wallet_address = data.get('wallet_address', '').strip()
        
        user_id = user['uid']
        fb_db.reference(f'/users/{user_id}/wallet_address').set(wallet_address)
        
        return jsonify({'status': 'success', 'message': 'Wallet updated successfully', 'wallet_address': wallet_address})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# উইথড্রয়াল এপিআই (Withdrawal API for Users)
# =========================================================================
@app.route('/api/v1/user/withdraw', methods=['POST'])
def request_withdrawal():
    try:
        db = load_db()
        user = get_current_user(db)
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        
        data = request.json or {}
        amount = float(data.get('amount', 0))
        method = data.get('method', 'TRC20').strip()
        address = data.get('address', '').strip()
        
        if amount <= 0:
            return jsonify({'status': 'error', 'message': 'সঠিক পরিমাণ এমাউন্ট লিখুন।'}), 400
        if amount > float(user.get('balance', 0)):
            return jsonify({'status': 'error', 'message': 'আপনার পর্যাপ্ত ব্যালেন্স নেই।'}), 400
        if not address:
            return jsonify({'status': 'error', 'message': 'উইথড্র গন্তব্য এড্রেস প্রয়োজন।'}), 400
        
        user_id = user['uid']
        new_balance = float(user.get('balance', 0)) - amount
        
        # ইউজার ব্যালেন্স সাবট্র্যাক্ট করা
        fb_db.reference(f'/users/{user_id}/balance').set(new_balance)
        
        # উইথড্র লগ তৈরি
        with_id = "wd_" + secrets.token_hex(8)
        withdrawal_data = {
            'id': with_id,
            'userId': user_id,
            'userEmail': user['email'],
            'userName': user['name'],
            'amount': amount,
            'method': method,
            'address': address,
            'status': 'pending',
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        fb_db.reference(f'/withdrawals/{with_id}').set(withdrawal_data)
        
        return jsonify({'status': 'success', 'message': 'উইথড্রয়াল রিকোয়েস্ট সফলভাবে জমা হয়েছে।', 'new_balance': new_balance})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# নম্বর ও ওটিপি রিসিভ এপিআই 
# =========================================================================
@app.route('/api/v1/getnum', methods=['GET', 'POST'])
def getnum():
    try:
        if request.method == 'POST':
            data = request.json or {}
            rid = data.get('rid')
            national = data.get('national', '1')
            remove_plus = data.get('remove_plus', '1')
        else:
            rid = request.args.get('rid')
            national = request.args.get('national', '1')
            remove_plus = request.args.get('remove_plus', '1')

        db = load_db()
        user = get_current_user(db)

        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key or Unauthorized'}), 403

        if not rid:
            return jsonify({'status': 'error', 'message': 'Range ID missing'}), 400

        clean_rid = str(rid).upper().replace('X', '').strip()
        user_id = user['uid']
        stex_data = None
        last_error = "No number available on this range"

        try:
            params = {'rid': clean_rid, 'national': int(national), 'remove_plus': int(remove_plus)}
            res = requests.get(f"{STEX_BASE_URL}/getnum", params=params, headers={'mauthapi': STEX_API_KEY}, timeout=10)
            if res.status_code == 200:
                json_res = res.json()
                meta = json_res.get('meta', {})
                if meta.get('status') == 'ok' or meta.get('code') == 200:
                    stex_data = json_res
                else:
                    last_error = json_res.get('message') or json_res.get('msg') or last_error
        except Exception as e:
            print("GET Attempt Failed:", e)

        if not stex_data:
            try:
                payload = {'rid': clean_rid, 'national': int(national), 'remove_plus': int(remove_plus)}
                res = requests.post(f"{STEX_BASE_URL}/getnum", json=payload, headers={'mauthapi': STEX_API_KEY}, timeout=10)
                if res.status_code == 200:
                    json_res = res.json()
                    meta = json_res.get('meta', {})
                    if meta.get('status') == 'ok' or meta.get('code') == 200:
                        stex_data = json_res
                    else:
                        last_error = json_res.get('message') or json_res.get('msg') or last_error
            except Exception as e:
                print("POST JSON Attempt Failed:", e)

        if not stex_data:
            return jsonify({'status': 'error', 'message': last_error}), 400

        data_payload = stex_data.get('data', {})
        number = data_payload.get('full_number') or data_payload.get('national_number') or data_payload.get('no_plus_number')
        country = data_payload.get('country', 'Guinea')
        operator = data_payload.get('operator', 'Mobile')

        alloc_id = "alloc_" + secrets.token_hex(8)
        allocation_data = {
            'id': alloc_id,
            'userId': user_id,
            'number': number,
            'rid': rid,
            'status': 'active',
            'country': country,
            'operator': operator,
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        fb_db.reference(f'/allocated_numbers/{alloc_id}').set(allocation_data)

        console_id = "con_" + secrets.token_hex(8)
        fb_db.reference(f'/live_console/{console_id}').set({
            'type': 'allocation',
            'message': f"Number {mask_number(number)} requested on range {rid}",
            'service': operator,
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

        return jsonify({
            'status': 'success',
            'number': number,
            'country': country,
            'operator': operator
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/user-allocations', methods=['GET'])
def get_user_allocations():
    try:
        db = load_db()
        user = get_current_user(db)

        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

        user_id = user['uid']
        otp_rate = float(user.get('otp_rate', 0.40))

        try:
            res = requests.get(f"{STEX_BASE_URL}/success-otp", headers={'mauthapi': STEX_API_KEY}, timeout=5)
            if res.status_code == 200:
                json_data = res.json()
                meta = json_data.get('meta', {})
                if meta.get('status') == 'ok' or meta.get('code') == 200:
                    otps = json_data.get('data', {}).get('otps', [])
                    for otp_item in otps:
                        otp_num = str(otp_item.get('number', '')).replace('+', '').strip()
                        
                        for alloc in db["allocated_numbers"]:
                            alloc_num = str(alloc.get('number', '')).replace('+', '').strip()
                            if alloc['status'] == 'active' and (alloc_num in otp_num or otp_num in alloc_num):
                                message = otp_item.get('message', '')
                                
                                otp_code = ""
                                match = re.search(r'\b\d{4,8}\b', message)
                                if match:
                                    otp_code = match.group(0)
                                else:
                                    otp_code = "SUCCESS"

                                service = 'generic'
                                msg_lower = message.lower()
                                if 'facebook' in msg_lower or 'fb' in msg_lower:
                                    service = 'facebook'
                                elif 'instagram' in msg_lower or 'ig' in msg_lower:
                                    service = 'instagram'
                                elif 'whatsapp' in msg_lower or 'wa' in msg_lower:
                                    service = 'whatsapp'
                                elif 'telegram' in msg_lower or 'tg' in msg_lower:
                                    service = 'telegram'
                                elif 'google' in msg_lower or 'g-' in msg_lower:
                                    service = 'google'

                                already_logged = False
                                for log in db["otp_logs"]:
                                    if log['number'] == alloc['number']:
                                        already_logged = True
                                        break
                                
                                if not already_logged:
                                    new_balance = float(user.get('balance', 0.0)) + otp_rate
                                    fb_db.reference(f'/users/{user_id}/balance').set(new_balance)
                                    
                                    otp_id = "otp_" + secrets.token_hex(8)
                                    fb_db.reference(f'/otp_logs/{otp_id}').set({
                                        'userId': user_id,
                                        'number': alloc['number'],
                                        'service': service,
                                        'otpCode': otp_code,
                                        'message': message,
                                        'revenue': otp_rate,
                                        'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
                                    })

                                alloc_id = alloc.get('id')
                                if alloc_id:
                                    fb_db.reference(f'/allocated_numbers/{alloc_id}').update({
                                        'status': 'completed',
                                        'otp': otp_code,
                                        'message': message
                                    })

                                console_id = "con_" + secrets.token_hex(8)
                                fb_db.reference(f'/live_console/{console_id}').set({
                                    'type': 'otp_success',
                                    'message': f"HIT! {service.upper()} OTP Received on {mask_number(alloc['number'])}!",
                                    'service': service,
                                    'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
                                })
        except Exception as e:
            print("Background OTP sync error:", e)

        # এক্সপায়ারড টাইমার চেক
        now = datetime.datetime.now(datetime.timezone.utc)
        user_allocs = [alloc for alloc in db["allocated_numbers"] if alloc['userId'] == user_id]
        
        for alloc in user_allocs:
            if alloc.get('status') == 'active':
                created_at_str = alloc.get('createdAt')
                if created_at_str:
                    created_at = parse_iso_datetime(created_at_str)
                    elapsed_seconds = (now - created_at).total_seconds()
                    if elapsed_seconds > (18 * 60):
                        alloc['status'] = 'expired'
                        alloc_id = alloc.get('id')
                        if alloc_id:
                            fb_db.reference(f'/allocated_numbers/{alloc_id}/status').set('expired')

        refreshed_db = load_db()
        refreshed_allocs = [a for a in refreshed_db["allocated_numbers"] if a['userId'] == user_id]
        refreshed_allocs.sort(key=lambda x: x.get('createdAt', ''), reverse=True)

        return jsonify({'status': 'success', 'allocations': refreshed_allocs})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/live-console', methods=['GET'])
def get_live_console():
    try:
        res = requests.get(f"{STEX_BASE_URL}/console", headers={'mauthapi': STEX_API_KEY}, timeout=5)
        if res.status_code == 200:
            stex_data = res.json()
            meta = stex_data.get('meta', {})
            if meta.get('status') == 'ok' or meta.get('code') == 200:
                hits = stex_data.get('data', {}).get('hits', [])
                data = []
                for hit in hits[:15]:
                    r = hit.get('range', 'N/A')
                    c_name = hit.get('country') or hit.get('country_name') or get_country_from_range(r)
                    data.append({
                        'range': r,
                        'service': hit.get('sid', 'Global'),
                        'message': hit.get('message', ''),
                        'time': hit.get('time', 0),
                        'country': c_name
                    })
                return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        print("STEX Console API Error:", e)
    return jsonify({'status': 'success', 'data': []})

@app.route('/api/v1/success-otp', methods=['GET'])
def success_otp():
    try:
        db = load_db()
        user = get_current_user(db)

        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

        user_logs = [log for log in db["otp_logs"] if log['userId'] == user['uid']]
        user_logs.sort(key=lambda x: x['createdAt'], reverse=True)

        data = []
        for d in user_logs[:15]:
            data.append({
                'number': d.get('number'),
                'service': d.get('service'),
                'otp_code': d.get('otpCode'),
                'message': d.get('message'),
                'revenue_earned': d.get('revenue'),
                'created_at': d.get('createdAt')
            })

        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# গ্লোবাল এডমিন কন্ট্রোল এপিআই সমূহ (API Routes for Admin)
# =========================================================================
@app.route('/api/v1/admin/login', methods=['POST'])
def admin_api_login():
    try:
        data = request.json or {}
        username = data.get('username')
        password = data.get('password')
        if username == ADMIN_USER and password == ADMIN_PASS:
            return jsonify({'status': 'success', 'token': ADMIN_STATIC_TOKEN})
        return jsonify({'status': 'error', 'message': 'Invalid Admin Credentials'}), 401
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/dashboard', methods=['GET'])
def admin_api_dashboard():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        db = load_db()
        total_users = len(db.get("users", {}))
        pending_users = sum(1 for u in db.get("users", {}).values() if u.get('status') == 'pending')
        total_allocations = len(db.get("allocated_numbers", []))
        total_otps = len(db.get("otp_logs", []))
        
        withdrawals = db.get("withdrawals", {})
        total_withdrawals = len(withdrawals) if isinstance(withdrawals, dict) else len(firebase_to_list(withdrawals))
        
        m_mode = is_maintenance()
        return jsonify({
            'status': 'success',
            'stats': {
                'total_users': total_users,
                'pending_users': pending_users,
                'total_allocations': total_allocations,
                'total_otps': total_otps,
                'total_withdrawals': total_withdrawals,
                'maintenance_mode': m_mode
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/users', methods=['GET'])
def admin_api_users():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        db = load_db()
        users_list = list(db.get("users", {}).values())
        users_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return jsonify({'status': 'success', 'users': users_list})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/users/update', methods=['POST'])
def admin_api_user_update():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.json or {}
        uid = data.get('uid')
        if not uid:
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400
        
        updates = {}
        if 'status' in data and data['status'] in ['approved', 'pending', 'banned']:
            updates['status'] = data['status']
        if 'balance' in data:
            updates['balance'] = float(data['balance'])
        if 'otp_rate' in data:
            updates['otp_rate'] = float(data['otp_rate'])
        if 'wallet_address' in data:
            updates['wallet_address'] = str(data['wallet_address']).strip()
        if 'api_key' in data:
            updates['api_key'] = str(data['api_key']).strip()
        if 'password' in data:
            updates['password'] = str(data['password']).strip()
            
        if updates:
            fb_db.reference(f'/users/{uid}').update(updates)
            
        return jsonify({'status': 'success', 'message': 'User updated successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/users/delete', methods=['POST'])
def admin_api_user_delete():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.json or {}
        uid = data.get('uid')
        if not uid:
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400
        
        fb_db.reference(f'/users/{uid}').delete()
        return jsonify({'status': 'success', 'message': 'User deleted successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/settings/toggle-maintenance', methods=['POST'])
def admin_api_toggle_maintenance():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.json or {}
        val = bool(data.get('maintenance_mode', False))
        fb_db.reference('/settings/maintenance_mode').set(val)
        return jsonify({'status': 'success', 'maintenance_mode': val})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/announcement', methods=['POST'])
def admin_api_announcement():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.json or {}
        msg = data.get('announcement', '').strip()
        fb_db.reference('/settings/announcement').set(msg)
        return jsonify({'status': 'success', 'message': 'Announcement updated'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/withdrawals', methods=['GET'])
def admin_get_withdrawals():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        db = load_db()
        withdrawals = db.get("withdrawals", {})
        if isinstance(withdrawals, dict):
            w_list = []
            for k, v in withdrawals.items():
                v['id'] = k
                w_list.append(v)
            withdrawals = w_list
        else:
            withdrawals = firebase_to_list(withdrawals)
        
        withdrawals.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return jsonify({'status': 'success', 'withdrawals': withdrawals})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/withdrawals/action', methods=['POST'])
def admin_withdrawal_action():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.json or {}
        wd_id = data.get('id')
        action = data.get('action') 
        
        if not wd_id or action not in ['approved', 'rejected']:
            return jsonify({'status': 'error', 'message': 'Invalid parameters'}), 400
        
        ref = fb_db.reference(f'/withdrawals/{wd_id}')
        wd_data = ref.get()
        if not wd_data:
            return jsonify({'status': 'error', 'message': 'Request not found'}), 404
        
        if wd_data.get('status') != 'pending':
            return jsonify({'status': 'error', 'message': 'Request already processed'}), 400
        
        if action == 'rejected':
            u_ref = fb_db.reference(f"/users/{wd_data['userId']}")
            user_data = u_ref.get()
            if user_data:
                new_bal = float(user_data.get('balance', 0)) + float(wd_data['amount'])
                u_ref.update({'balance': new_bal})
                
        ref.update({'status': action})
        return jsonify({'status': 'success', 'message': f'Withdrawal {action} successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/backup', methods=['GET'])
def admin_api_backup():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        db = load_db()
        return jsonify({'status': 'success', 'data': db})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/allocations', methods=['GET'])
def admin_api_allocations():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        db = load_db()
        allocs = db.get("allocated_numbers", [])
        allocs.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return jsonify({'status': 'success', 'allocations': allocs})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/otp-logs', methods=['GET'])
def admin_api_otp_logs():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        db = load_db()
        logs = db.get("otp_logs", [])
        logs.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return jsonify({'status': 'success', 'otp_logs': logs})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# ফ্রন্টএন্ড UI পরিবেশন 
# =========================================================================
@app.route('/', methods=['GET'])
def index():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>MINO SMS PANEL</title>
      <script src="https://cdn.tailwindcss.com"></script>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/vue/3.3.4/vue.global.prod.min.js"></script>
      <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
      <style>
        [v-cloak] { display: none; }
        body { background-color: #F8FAFC; }
      </style>
    </head>
    <body class="text-slate-700 font-sans select-none pb-16 md:pb-0">
      
      <div id="app">

        <!-- লোডিং স্ক্রিন -->
        <div v-if="!userLoaded" class="fixed inset-0 bg-slate-50 flex flex-col items-center justify-center space-y-4 z-[99999]">
          <div class="h-12 w-12 border-4 border-[#0088CC] border-t-transparent rounded-full animate-spin"></div>
          <p class="text-xs font-black text-[#0088CC] uppercase tracking-widest animate-pulse">MINO PANEL LOADING...</p>
        </div>

        <div v-cloak v-if="userLoaded">

          <!-- কপি টোস্ট নোটিফিকেশন -->
          <div v-if="showToast" class="fixed top-5 left-1/2 -translate-x-1/2 bg-[#0088CC] text-white font-black text-xs px-5 py-3.5 rounded-2xl shadow-xl z-[9999] transition animate-bounce">
            {{ toastMessage }}
          </div>

          <!-- লগইন / সাইনআপ উইন্ডো -->
          <div v-if="!user" class="min-h-screen flex items-center justify-center p-4">
            <div class="bg-white p-6 sm:p-8 rounded-3xl border border-slate-200 shadow-sm max-w-md w-full space-y-6">
              <div class="text-center space-y-2">
                <span class="px-3 py-1.5 bg-[#0088CC] rounded-2xl flex items-center justify-center text-white font-black text-lg mx-auto shadow-md w-max">MINO</span>
                <h1 class="text-xl font-black text-slate-900">MINO SMS PANEL</h1>
                <p class="text-[10px] font-semibold text-[#0088CC] uppercase tracking-widest">{{ isRegistering ? 'Register account' : 'Sign in to network' }}</p>
              </div>

              <form @submit.prevent="handleAuth" class="space-y-4">
                <div v-if="isRegistering">
                  <label class="text-xs font-bold text-slate-500">Your Name</label>
                  <input type="text" required v-model="authName" placeholder="Gopal Var" class="w-full mt-1.5 p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-[#0088CC] transition" />
                </div>
                <div>
                  <label class="text-xs font-bold text-slate-500">Email</label>
                  <input type="email" required v-model="authEmail" placeholder="gopal@network.com" class="w-full mt-1.5 p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-[#0088CC] transition" />
                </div>
                <div>
                  <label class="text-xs font-bold text-slate-500">Password</label>
                  <input type="password" required v-model="authPassword" placeholder="••••••••" class="w-full mt-1.5 p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-[#0088CC] transition" />
                </div>

                <button type="submit" :disabled="authLoading" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-3.5 rounded-xl text-sm shadow-md transition disabled:bg-slate-300">
                  {{ authLoading ? 'Please wait...' : (isRegistering ? 'REGISTER' : 'LOG IN') }}
                </button>
              </form>

              <div class="text-center">
                <button @click="isRegistering = !isRegistering" class="text-xs font-semibold text-[#0088CC] hover:underline">
                  {{ isRegistering ? 'Already have an account? Log In' : "Create an Account" }}
                </button>
              </div>
            </div>
          </div>

          <!-- মেইন প্যানেল ড্যাশবোর্ড -->
          <div v-else class="min-h-screen flex flex-col md:flex-row">
            
            <!-- ডেস্কটপ সাইডবার -->
            <aside class="hidden md:flex w-64 bg-white border-r border-slate-200 flex-col shrink-0">
              <div class="p-6 border-b border-slate-100 flex items-center gap-3">
                <span class="px-2 py-1 bg-[#0088CC] rounded-lg flex items-center justify-center text-white font-black text-sm">MINO</span>
                <span class="text-lg font-black text-slate-950">MINO SMS</span>
              </div>

              <nav class="flex-1 p-4 space-y-1">
                <button @click="currentTab = 'dashboard'" :class="currentTab === 'dashboard' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-house"></i> ড্যাশবোর্ড
                </button>
                <button @click="currentTab = 'get-number'" :class="currentTab === 'get-number' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-mobile-screen"></i> নাম্বার নিন
                </button>
                <button @click="currentTab = 'console'" :class="currentTab === 'console' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-terminal"></i> কনসোল
                </button>
                <button @click="currentTab = 'payment'" :class="currentTab === 'payment' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-wallet"></i> পেমেন্ট
                </button>
                <button @click="currentTab = 'profile'" :class="currentTab === 'profile' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-user"></i> প্রোফাইল
                </button>
              </nav>

              <div class="p-4 border-t border-slate-100 flex items-center gap-3">
                <div class="h-9 w-9 bg-[#0088CC] rounded-full flex items-center justify-center text-white font-bold text-sm">
                  {{ user?.name ? user.name.slice(0, 2).toUpperCase() : 'US' }}
                </div>
                <div class="flex-1 overflow-hidden">
                  <p class="text-xs font-black text-slate-800 truncate">{{ user?.name || 'User' }}</p>
                  <p class="text-[10px] text-slate-400 truncate">{{ user?.email }}</p>
                </div>
                <button @click="signOut" class="text-slate-400 hover:text-rose-600"><i class="fa-solid fa-right-from-bracket"></i></button>
              </div>
            </aside>

            <!-- মোবাইল বটম নেভিগেশন -->
            <div class="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 flex justify-around py-2 z-50 shadow-lg px-2">
              <button @click="currentTab = 'dashboard'" :class="currentTab === 'dashboard' ? 'text-[#0088CC]' : 'text-slate-400'" class="flex flex-col items-center gap-1 text-[10px] font-bold py-1 flex-1">
                <i class="fa-solid fa-house text-lg"></i>
                <span>হোম</span>
              </button>
              <button @click="currentTab = 'get-number'" :class="currentTab === 'get-number' ? 'text-[#0088CC]' : 'text-slate-400'" class="flex flex-col items-center gap-1 text-[10px] font-bold py-1 flex-1">
                <i class="fa-solid fa-mobile-screen text-lg"></i>
                <span>নাম্বার নিন</span>
              </button>
              <button @click="currentTab = 'console'" :class="currentTab === 'console' ? 'text-[#0088CC]' : 'text-slate-400'" class="flex flex-col items-center gap-1 text-[10px] font-bold py-1 flex-1">
                <i class="fa-solid fa-terminal text-lg"></i>
                <span>কনসোল</span>
              </button>
              <button @click="currentTab = 'payment'" :class="currentTab === 'payment' ? 'text-[#0088CC]' : 'text-slate-400'" class="flex flex-col items-center gap-1 text-[10px] font-bold py-1 flex-1">
                <i class="fa-solid fa-wallet text-lg"></i>
                <span>পেমেন্ট</span>
              </button>
              <button @click="currentTab = 'profile'" :class="currentTab === 'profile' ? 'text-[#0088CC]' : 'text-slate-400'" class="flex flex-col items-center gap-1 text-[10px] font-bold py-1 flex-1">
                <i class="fa-solid fa-user text-lg"></i>
                <span>প্রোফাইল</span>
              </button>
            </div>

            <!-- মেইন কন্টেন্ট এরিয়া -->
            <main class="flex-1 p-4 md:p-8 space-y-6 overflow-y-auto pb-24 md:pb-8">
              
              <header class="flex justify-between items-center border-b border-slate-200 pb-4">
                <div class="flex items-center gap-2">
                  <span class="h-2.5 w-2.5 bg-[#0088CC] rounded-full"></span>
                  <h2 class="text-md md:text-lg font-black text-slate-900 capitalize">{{ currentTab.replace('-', ' ') }}</h2>
                </div>
                <div class="flex items-center gap-2">
                  <span class="bg-[#0088CC] text-white text-[10px] md:text-xs font-bold px-3 py-1.5 rounded-full shadow-sm">{{ user?.name || 'User' }}</span>
                  <button @click="signOut" class="md:hidden text-slate-400 hover:text-rose-600 p-2"><i class="fa-solid fa-right-from-bracket text-lg"></i></button>
                </div>
              </header>

              <!-- গ্লোবাল অ্যানাউন্সমেন্ট ব্যানার -->
              <div v-if="announcement" class="bg-indigo-50 border border-indigo-200 text-indigo-800 px-5 py-3 rounded-2xl text-xs font-bold flex items-center gap-2 animate-pulse">
                <i class="fa-solid fa-bullhorn text-[#0088CC]"></i>
                <span>{{ announcement }}</span>
              </div>

              <!-- ==================== সেকশন ১: ড্যাশবোর্ড ==================== -->
              <div v-if="currentTab === 'dashboard'" class="space-y-6">
                <div>
                  <h3 class="text-[10px] md:text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">WALLET & REPORT</h3>
                  <div class="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-4">
                    
                    <div class="bg-white p-4 md:p-5 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-start md:items-center gap-3">
                      <div class="bg-emerald-50 h-10 w-10 rounded-xl flex items-center justify-center text-emerald-600 shrink-0"><i class="fa-solid fa-wallet text-md"></i></div>
                      <div>
                        <p class="text-[10px] text-slate-400 font-bold">ব্যালেন্স</p>
                        <h4 class="text-sm md:text-lg font-bold text-slate-900 mt-0.5">৳ {{ parseFloat(profile ? profile.balance : 0).toFixed(2) }}</h4>
                      </div>
                    </div>

                    <div class="bg-white p-4 md:p-5 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-start md:items-center gap-3">
                      <div class="bg-amber-50 h-10 w-10 rounded-xl flex items-center justify-center text-amber-600 shrink-0"><i class="fa-solid fa-tag text-md"></i></div>
                      <div>
                        <p class="text-[10px] text-slate-400 font-bold">ওটিপি রেট</p>
                        <h4 class="text-sm md:text-lg font-bold text-slate-900 mt-0.5">৳ {{ parseFloat(profile ? profile.otp_rate : 0.40).toFixed(2) }}</h4>
                      </div>
                    </div>

                    <div class="bg-white p-4 md:p-5 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-start md:items-center gap-3 col-span-2 md:col-span-1">
                      <div class="bg-blue-50 h-10 w-10 rounded-xl flex items-center justify-center text-blue-600 shrink-0"><i class="fa-solid fa-box text-md"></i></div>
                      <div>
                        <p class="text-[10px] text-slate-400 font-bold">আজকের মোট ওটিপি</p>
                        <h4 class="text-sm md:text-lg font-bold text-slate-900 mt-0.5">{{ successOtps.length }} টি</h4>
                      </div>
                    </div>

                  </div>
                </div>

                <div class="bg-white rounded-3xl border border-slate-200 shadow-xs overflow-hidden">
                  <div class="p-4 border-b border-slate-100 bg-slate-50/50">
                    <h4 class="font-bold text-xs text-slate-400 uppercase tracking-widest">সর্বশেষ ওটিপি রিপোর্ট</h4>
                  </div>

                  <div class="block divide-y divide-slate-100">
                    <div v-if="successOtps.length === 0" class="p-8 text-center text-slate-400 font-semibold text-xs">
                      কোনো ওটিপি ডাটা পাওয়া যায়নি।
                    </div>
                    <div v-else v-for="log in successOtps" :key="log.created_at" class="p-4 space-y-2 text-xs">
                      <div class="flex justify-between items-center">
                        <span class="font-bold text-slate-800 text-sm">{{ log.number }}</span>
                        <span class="px-2 py-0.5 bg-[#0088CC]/10 text-[#0088CC] rounded text-[9px] font-bold uppercase">{{ log.service }}</span>
                      </div>
                      <div class="flex justify-between items-center bg-slate-50 p-2 rounded-xl">
                        <span class="text-slate-400 font-bold">ওটিপি কোড:</span>
                        <span class="font-bold text-emerald-600 text-sm">{{ log.otp_code }}</span>
                      </div>
                      <p class="text-[11px] text-slate-500 leading-relaxed font-medium"><strong class="text-slate-700">মেসেজ:</strong> {{ log.message }}</p>
                    </div>
                  </div>

                </div>

              </div>

              <!-- ==================== সেকশন ২: নম্বর নিন (৩টি কলামে বিভক্ত ও স্টাইলিশ) ==================== -->
              <div v-if="currentTab === 'get-number'" class="space-y-6">
                
                <div class="bg-white p-5 md:p-6 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <div class="flex items-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                    <i class="fa-solid fa-mobile-button text-[#0088CC]"></i> আপনার কাঙ্ক্ষিত রেঞ্জ (Your Range)
                  </div>
                  <input type="text" v-model="rid" class="w-full p-4 bg-slate-50 border border-slate-200 rounded-2xl text-lg font-black outline-none tracking-wider text-[#0088CC] focus:border-[#0088CC] text-center" />
                  
                  <div class="flex items-center gap-4 text-xs font-bold text-slate-400 py-1 justify-center">
                    <label class="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" v-model="nationalFormat" class="rounded text-[#0088CC]" /> National Format
                    </label>
                    <label class="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" v-model="removePlus" class="rounded text-[#0088CC]" /> Remove (+)
                    </label>
                  </div>

                  <button @click="handleGetNumber" :disabled="loadingNumber" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-4 rounded-2xl shadow-md transition flex items-center justify-center gap-2 disabled:bg-slate-300 active:scale-[0.98]">
                    <i v-if="loadingNumber" class="fa-solid fa-spinner animate-spin"></i>
                    <span class="tracking-widest font-black"><i class="fa-solid fa-bolt mr-1"></i> GET NUMBER</span>
                  </button>
                </div>

                <div class="space-y-4">
                  
                  <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 px-2">
                    <input type="text" v-model="searchQuery" placeholder="নম্বর বা দেশ দিয়ে খুঁজুন..." class="w-full sm:w-64 p-3 bg-white border border-slate-200 rounded-2xl text-xs font-semibold outline-none focus:border-[#0088CC]" />
                    <div class="flex gap-2 text-[10px] font-bold text-slate-400 items-center">
                      <button @click="prevPage" :disabled="currentPage === 1" class="bg-white border rounded-xl px-3 py-1.5 disabled:opacity-50 shadow-xs">Prev</button>
                      <span>Page {{ currentPage }} of {{ totalPages }}</span>
                      <button @click="nextPage" :disabled="currentPage === totalPages" class="bg-white border rounded-xl px-3 py-1.5 disabled:opacity-50 shadow-xs">Next</button>
                    </div>
                  </div>

                  <div v-if="paginatedAllocations.length === 0" class="bg-white p-12 text-center text-slate-400 border rounded-3xl font-semibold text-xs">
                    কোনো নম্বর তালিকা পাওয়া যায়নি।
                  </div>

                  <!-- ৩টি সেকশনে বিভক্ত নম্বর বরাদ্দ উইজেট -->
                  <div v-else class="space-y-4">
                    <div v-for="alloc in paginatedAllocations" :key="alloc.createdAt" class="bg-white rounded-3xl border border-slate-200 overflow-hidden shadow-xs hover:shadow-sm hover:border-slate-300 transition">
                      <div class="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-slate-100">
                        
                        <!-- ১ম সেকশন: দেশ ও নম্বর (Country & Number) -->
                        <div class="p-5 flex flex-col justify-between space-y-2">
                          <div>
                            <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Country & Number</p>
                            <div @click="copyToClipboard(alloc.number)" class="flex items-center gap-2 mt-1.5 cursor-pointer hover:opacity-80 active:scale-95 transition w-max">
                              <span class="font-black text-slate-800 text-base tracking-wider">{{ alloc.number }}</span>
                              <i class="fa-regular fa-copy text-xs text-[#0088CC]"></i>
                            </div>
                          </div>
                          <div class="pt-2">
                            <p class="font-black text-slate-700 text-xs uppercase">{{ alloc.country }}</p>
                            <p class="text-[9px] text-slate-400 font-black uppercase mt-0.5">{{ alloc.operator }}</p>
                          </div>
                        </div>

                        <!-- ২য় সেকশন: ওটিপি ও মেসেজ (SMS) -->
                        <div class="p-5 flex flex-col justify-center min-w-0">
                          <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-2">SMS Message</p>
                          
                          <div v-if="alloc.status === 'active'" class="text-xs text-amber-600 font-black italic animate-pulse flex items-center gap-1.5">
                            <i class="fa-solid fa-spinner animate-spin"></i> Waiting for incoming SMS...
                          </div>
                          
                          <div v-else-if="alloc.status === 'completed'" class="flex flex-col gap-2">
                            <!-- ৩য় ফটো সমাধান: ছোট বক্স, শুধুমাত্র ওটিপি কোড দেখাবে এবং ক্লিক করলে সম্পূর্ণ মেসেজ কপি হবে -->
                            <div @click="copyFullSms(alloc.message)" class="bg-emerald-50 hover:bg-emerald-100 border-2 border-emerald-200 p-3 rounded-2xl text-emerald-800 text-center cursor-pointer active:scale-95 transition-all flex items-center justify-between gap-3 group">
                              <div class="text-left">
                                <span class="text-[9px] text-emerald-600 font-bold uppercase tracking-wider block">Extracted OTP Code</span>
                                <span class="text-lg font-black text-emerald-800 tracking-widest mt-0.5 block">
                                  {{ alloc.otp }}
                                </span>
                              </div>
                              <div class="bg-emerald-500 group-hover:bg-emerald-600 text-white h-8 w-8 rounded-xl flex items-center justify-center shrink-0 shadow-sm transition" title="ক্লিক করলেই সম্পূর্ণ ওটিপি মেসেজ কপি হবে">
                                <i class="fa-regular fa-copy text-xs"></i>
                              </div>
                            </div>
                            <span class="text-[9px] text-slate-400 font-medium italic">*ওটিপি বক্সে ক্লিক করলে সম্পূর্ণ মেসেজটি কপি হবে।</span>
                          </div>
                          
                          <div v-else class="text-xs text-rose-500 font-bold flex items-center gap-1">
                            <i class="fa-solid fa-circle-exclamation"></i> Banned / Closed (18 mins over)
                          </div>
                        </div>

                        <!-- ৩য় সেকশন: সময় (Time) -->
                        <div class="p-5 flex flex-col justify-between items-start md:items-end space-y-3">
                          <div class="w-full md:text-right">
                            <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Remaining Time</p>
                            <div class="inline-block mt-2 bg-slate-50 border border-slate-200 text-slate-700 text-sm font-black py-1.5 px-4 rounded-full tracking-wider min-w-[80px] text-center shadow-inner">
                              {{ alloc.status === 'active' && alloc.timeLeft > 0 ? formatTime(alloc.timeLeft) : '--:--' }}
                            </div>
                          </div>
                          <div class="w-full flex justify-between md:justify-end gap-1.5">
                            <span v-if="alloc.status === 'active'" class="bg-amber-50 text-amber-600 text-[9px] font-black px-2.5 py-1 rounded-full uppercase flex items-center gap-1">
                              <i class="fa-solid fa-spinner animate-spin text-[8px]"></i> PENDING
                            </span>
                            <span v-else-if="alloc.status === 'completed'" class="bg-emerald-100 text-emerald-800 text-[9px] font-black px-2.5 py-1 rounded-full uppercase">
                              SUCCESS
                            </span>
                            <span v-else class="bg-slate-100 text-slate-500 text-[9px] font-black px-2.5 py-1 rounded-full uppercase">
                              EXPIRED
                            </span>
                          </div>
                        </div>

                      </div>
                    </div>
                  </div>

                </div>

              </div>

              <!-- ==================== সেকশন ৩: কনসোল ==================== -->
              <div v-if="currentTab === 'console'" class="space-y-6">
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs flex justify-between items-center">
                  <div>
                    <div class="flex items-center gap-2">
                      <i class="fa-solid fa-satellite-dish text-[#0088CC] text-lg animate-pulse"></i>
                      <h2 class="text-md font-black text-slate-900">GLOBAL INTERCEPT RADAR</h2>
                    </div>
                    <p class="text-[10px] text-slate-400 font-medium mt-1">যেকোনো কার্ডের উপর ক্লিক করলেই এর রেঞ্জ কপি হয়ে যাবে।</p>
                  </div>
                </div>

                <div class="space-y-3">
                  <div v-if="liveLogs.length === 0" class="p-12 text-slate-400 text-center font-semibold bg-white border rounded-3xl text-xs">সিগন্যাল ট্র্যাকিং ইনিশিয়ালাইজ হচ্ছে...</div>
                  
                  <div v-else v-for="log in liveLogs" :key="log.time" @click="copyToClipboard(log.range)" class="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs cursor-pointer hover:border-[#0088CC] hover:bg-slate-50/50 transition active:scale-[0.99] space-y-2">
                    <div class="flex justify-between items-center border-b border-slate-100 pb-1.5">
                      <span class="text-sm font-black text-[#0088CC] uppercase tracking-wide">
                        {{ log.service }}
                      </span>
                      <span class="bg-slate-100 text-slate-500 text-[9px] font-bold px-2 py-0.5 rounded uppercase">
                        {{ log.country }} (Click to Copy)
                      </span>
                    </div>
                    <div class="space-y-1">
                      <p class="font-mono font-bold text-slate-800 text-[11px] leading-tight break-words">
                        {{ log.message }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ==================== সেকশন ৪: পেমেন্ট এবং উইথড্রয়াল ==================== -->
              <div v-if="currentTab === 'payment'" class="space-y-6">
                
                <div class="bg-white p-5 rounded-3xl border border-[#0088CC]/20 shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-800 flex items-center gap-2"><i class="fa-solid fa-wallet text-[#0088CC]"></i> ওয়ালেট এড্রেস সেট করুন (Binance / TRC20)</h3>
                  
                  <div class="bg-indigo-50/50 border border-indigo-100 p-4 rounded-xl flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                    <div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase">BINANCE PAY ID / TRC20 ADDRESS</p>
                      <p class="font-mono font-black text-indigo-700 mt-1 select-all break-all">{{ user?.wallet_address || 'ওয়ালেট সেট করা নেই' }}</p>
                    </div>
                    <span class="bg-[#0088CC] text-white text-[10px] font-bold px-2.5 py-1 rounded-full shadow-sm"><i class="fa-brands fa-bitcoin"></i> TRC20</span>
                  </div>

                  <div class="flex flex-col sm:flex-row gap-2 pt-2">
                    <input type="text" v-model="walletAddressInput" placeholder="আপনার Binance Pay ID বা TRC20 এড্রেস লিখুন" class="flex-1 p-3.5 bg-slate-50 border border-slate-200 rounded-2xl text-xs font-semibold outline-none focus:border-[#0088CC] transition" />
                    <button @click="handleUpdateWallet" :disabled="walletLoading" class="bg-[#0088CC] hover:bg-[#0077B5] text-white font-black px-5 py-3.5 rounded-2xl text-xs tracking-wider transition active:scale-95 disabled:bg-slate-300 shrink-0">
                      {{ walletLoading ? 'সংরক্ষণ হচ্ছে...' : 'ওয়ালেট সেভ করুন' }}
                    </button>
                  </div>
                </div>

                <!-- উইথড্রয়াল রিকোয়েস্ট উইজেট -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-800 flex items-center gap-2">
                    <i class="fa-solid fa-hand-holding-dollar text-emerald-600"></i> উইথড্রয়াল রিকোয়েস্ট (Withdraw Request)
                  </h3>
                  <p class="text-[11px] text-slate-400 leading-relaxed font-semibold">আপনার আর্ন করা টাকা আপনার সেট করা ওয়ালেটে উইথড্র করতে নিচে এমাউন্ট দিয়ে রিকোয়েস্ট পাঠান।</p>
                  
                  <div class="grid sm:grid-cols-2 gap-3 text-xs font-bold">
                    <div>
                      <label class="text-slate-400">উইথড্র এমাউন্ট (৳)</label>
                      <input type="number" step="1" v-model="withdrawAmount" placeholder="যেমন: 50" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl" />
                    </div>
                    <div>
                      <label class="text-slate-400">পেমেন্ট মেথড</label>
                      <select v-model="withdrawMethod" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl">
                        <option value="TRC20">USDT (TRC20)</option>
                        <option value="Binance Pay">Binance Pay ID</option>
                      </select>
                    </div>
                  </div>

                  <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 border-t pt-3">
                    <div class="text-[11px] font-bold text-slate-500">
                      গন্তব্য এড্রেস: <span class="text-[#0088CC] font-mono select-all">{{ user?.wallet_address || 'প্রোফাইল থেকে আগে ওয়ালেট সেট করুন।' }}</span>
                    </div>
                    <button @click="submitWithdrawal" :disabled="!user?.wallet_address || withdrawAmount <= 0" class="bg-emerald-600 hover:bg-emerald-700 text-white font-black px-6 py-3 rounded-xl text-xs transition flex items-center gap-1.5 disabled:bg-slate-200 shadow-sm active:scale-95">
                      <i class="fa-solid fa-paper-plane"></i> উইথড্র রিকোয়েস্ট পাঠান
                    </button>
                  </div>
                </div>

                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs flex justify-between items-center">
                  <div>
                    <p class="text-[10px] font-bold text-slate-400 uppercase">মোট অর্জিত আয়</p>
                    <h2 class="text-xl font-black text-[#0088CC] mt-0.5">৳ {{ parseFloat(profile ? profile.balance : 0).toFixed(2) }}</h2>
                  </div>
                  <div class="bg-[#0088CC]/10 h-10 w-10 rounded-full flex items-center justify-center text-[#0088CC] text-md font-bold">৳</div>
                </div>
              </div>

              <!-- ==================== সেকশন ৫: প্রোফাইল (API Docs আইকন সহ) ==================== -->
              <div v-if="currentTab === 'profile'" class="space-y-6">
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs flex items-center gap-4">
                  <div class="h-14 w-14 bg-[#0088CC] text-white font-black text-sm rounded-full flex items-center justify-center">
                    {{ user?.name ? user.name.slice(0, 2).toUpperCase() : 'US' }}
                  </div>
                  <div class="flex-1 overflow-hidden">
                    <p class="text-sm font-black text-slate-800">{{ user?.name || 'User' }}</p>
                    <p class="text-[10px] text-slate-400 truncate">{{ user?.email }}</p>
                  </div>
                </div>

                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-3 text-xs">
                  <h3 class="font-bold text-slate-800 border-b border-slate-100 pb-2">প্রোফাইল ইনফো</h3>
                  <div class="space-y-4 font-semibold">
                    <p class="text-slate-500">ইউজার আইডি: <span class="text-slate-800 font-bold ml-1">{{ profile ? profile.uid : 'N/A' }}</span></p>
                    
                    <div class="space-y-2">
                      <p class="text-slate-500">এپیআই কি:</p>
                      
                      <div v-if="profile && profile.api_key" class="flex flex-col gap-2">
                        <span class="text-slate-800 font-mono text-[10px] bg-slate-50 px-3 py-2 rounded border break-all select-all">
                          {{ profile.api_key }}
                        </span>
                        <div class="flex gap-2">
                          <button @click="copyToClipboard(profile.api_key)" class="bg-[#0088CC]/10 text-[#0088CC] font-bold px-3 py-1.5 rounded-xl text-[10px] hover:bg-[#0088CC]/20 transition flex items-center gap-1">
                            কপি করুন <i class="fa-solid fa-copy"></i>
                          </button>
                        </div>
                      </div>
                      
                      <div v-else class="space-y-2">
                        <p class="text-amber-600 text-[10px] font-bold"><i class="fa-solid fa-triangle-exclamation"></i> কোনো এپیআই কি জেনারেট করা নেই। নিচের বাটনে ক্লিক করে স্থায়ী এপিআই কি তৈরি করুন।</p>
                        <button @click="handleGenerateApiKey" :disabled="apiGenLoading" class="bg-emerald-600 hover:bg-emerald-700 text-white font-black px-4 py-2.5 rounded-2xl text-[11px] tracking-wider transition active:scale-95 disabled:bg-slate-300">
                          {{ apiGenLoading ? 'তৈরি হচ্ছে...' : 'GENERATE API KEY' }}
                        </button>
                      </div>
                    </div>

                    <!-- ১ম ফটো সমাধান: এপিআই ডক্স এবং লাইভ টেস্ট ল্যাব আইকন/বাটন -->
                    <div class="mt-4 border-t pt-3 flex items-center justify-between">
                      <span class="text-slate-500 font-bold">API Documentation & Test Lab:</span>
                      <button @click="currentTab = 'api-docs'" class="bg-[#0088CC]/10 hover:bg-[#0088CC]/20 text-[#0088CC] font-black px-3.5 py-2 rounded-xl text-[10px] flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-code"></i> API Docs & Test Lab
                      </button>
                    </div>

                  </div>
                </div>
              </div>

              <!-- ==================== সেকশন ৬: এপিআই ডক্স ও টেস্ট ল্যাব (১ম ফটো সমাধান) ==================== -->
              <div v-if="currentTab === 'api-docs'" class="space-y-6">
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <div class="flex items-center gap-2">
                    <i class="fa-solid fa-terminal text-[#0088CC] text-lg"></i>
                    <h2 class="text-md font-black text-slate-900">Mino API Documentation & Test Lab</h2>
                  </div>
                  <p class="text-xs text-slate-500 leading-relaxed font-semibold">
                    আপনার এপিআই কি ব্যবহার করে সরাসরি থার্ড-পার্টি স্ক্রিপ্ট বা সফটওয়্যারে Mino Panel ইন্টিগ্রেট করুন। নিচে এপিআই রিকোয়েস্টের নিয়মাবলী ও লাইভ টেস্ট ল্যাব দেওয়া হলো।
                  </p>
                </div>

                <!-- এপিআই রুট ১: Get Number -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-3">
                  <span class="bg-[#0088CC] text-white text-[9px] font-black px-2.5 py-1 rounded uppercase tracking-wider">GET /api/v1/getnum</span>
                  <h3 class="text-xs font-black text-slate-800 mt-2">১. নম্বর বুকিং করার এপিআই রুট</h3>
                  <p class="text-[11px] text-slate-400">নতুন নম্বর বরাদ্দ করতে এই রুটে GET বা POST রিকোয়েস্ট পাঠান।</p>
                  <div class="bg-slate-50 p-3 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto break-all leading-relaxed border">
                    {{ apiBaseUrl }}/api/v1/getnum?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}&rid=2250789XXX&national=1&remove_plus=1
                  </div>
                </div>

                <!-- লাইভ এপিআই টেস্ট ল্যাব -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <h3 class="text-xs font-black text-slate-800 flex items-center gap-2">
                    <i class="fa-solid fa-flask text-emerald-600"></i> লাইভ এপিআই টেস্ট ল্যাব (Live Tester)
                  </h3>
                  <div class="grid sm:grid-cols-2 gap-3 text-xs font-bold">
                    <div>
                      <label class="text-slate-400">এপিআই রেঞ্জ (Range)</label>
                      <input type="text" v-model="testRange" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl" />
                    </div>
                    <div class="flex items-end">
                      <button @click="runLiveApiTest" :disabled="testApiLoading" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-3 rounded-xl transition flex items-center justify-center gap-1.5 disabled:bg-slate-200">
                        <i v-if="testApiLoading" class="fa-solid fa-spinner animate-spin"></i>
                        <span>টেস্ট রিকোয়েস্ট রান করুন</span>
                      </button>
                    </div>
                  </div>
                  <!-- টেস্ট রেসপন্স -->
                  <div v-if="testApiResponse" class="mt-3">
                    <span class="text-[9px] text-slate-400 font-bold uppercase block mb-1">API Response:</span>
                    <pre class="bg-slate-900 text-emerald-400 p-4 rounded-2xl text-[10px] font-mono overflow-x-auto select-all leading-relaxed shadow-inner">{{ testApiResponse }}</pre>
                  </div>
                </div>
              </div>

            </main>
          </div>
        </div>

      </div>

      <script>
        const { createApp, ref, onMounted, watch, computed } = Vue;

        createApp({
          setup() {
            const userLoaded = ref(false); 
            const user = ref(null);
            const profile = ref(null);
            const authName = ref('');
            const authEmail = ref('');
            const authPassword = ref('');
            const isRegistering = ref(false);
            const authLoading = ref(false);

            const currentTab = ref('dashboard');
            const announcement = ref('');

            const rid = ref('2250789XXX'); 
            const nationalFormat = ref(true); 
            const removePlus = ref(true);     
            
            const activeNumber = ref(null);
            const activeCountry = ref('');
            const activeOperator = ref('');
            const otpResult = ref(null);
            const loadingNumber = ref(false);
            const liveLogs = ref([]);
            const successOtps = ref([]);
            
            const walletAddressInput = ref('');
            const walletLoading = ref(false);
            const apiGenLoading = ref(false);

            const searchQuery = ref('');

            const allocations = ref([]);
            const currentPage = ref(1);
            const itemsPerPage = 200;

            const showToast = ref(false);
            const toastMessage = ref('');
            let pollingTimer = null;

            // লাইভ টেস্ট ল্যাব ভেরিয়েবলস
            const testRange = ref('2250789XXX');
            const testApiLoading = ref(false);
            const testApiResponse = ref(null);
            const apiBaseUrl = ref(window.location.origin);

            // উইথড্রয়াল ভেরিয়েবলস
            const withdrawAmount = ref('');
            const withdrawMethod = ref('TRC20');

            const playBeep = () => {
              try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.type = "sine";
                osc.frequency.setValueAtTime(880, ctx.currentTime); 
                gain.gain.setValueAtTime(0.1, ctx.currentTime);
                osc.start();
                osc.stop(ctx.currentTime + 0.15); 
              } catch (e) {
                console.log("Audio notify failed:", e);
              }
            };

            const triggerToast = (msg) => {
              toastMessage.value = msg;
              showToast.value = true;
              setTimeout(() => {
                showToast.value = false;
              }, 2000);
            };

            const copyToClipboard = (text) => {
              if (!text) return;
              navigator.clipboard.writeText(text);
              triggerToast("কপি করা হয়েছে: " + text);
            };

            const copyFullSms = (messageText) => {
              if (!messageText) return;
              navigator.clipboard.writeText(messageText);
              triggerToast("সম্পূর্ণ ওটিপি মেসেজ কপি হয়েছে! ✅");
            };

            const filteredAllocations = computed(() => {
              if (!allocations.value) return [];
              const q = searchQuery.value.toLowerCase().trim();
              if (!q) return allocations.value;
              return allocations.value.filter(alloc => 
                (alloc.number && alloc.number.includes(q)) || 
                (alloc.country && alloc.country.toLowerCase().includes(q)) ||
                (alloc.operator && alloc.operator.toLowerCase().includes(q))
              );
            });

            const paginatedAllocations = computed(() => {
              if (!filteredAllocations.value) return [];
              const start = (currentPage.value - 1) * itemsPerPage;
              const end = start + itemsPerPage;
              return filteredAllocations.value.slice(start, end);
            });

            const totalPages = computed(() => {
              return Math.ceil(filteredAllocations.value.length / itemsPerPage) || 1;
            });

            const prevPage = () => {
              if (currentPage.value > 1) currentPage.value--;
            };

            const nextPage = () => {
              if (currentPage.value < totalPages.value) currentPage.value++;
            };

            const updateTimers = () => {
              if (!allocations.value) return;
              allocations.value.forEach(alloc => {
                if (alloc.status === 'active') {
                  const createdAt = new Date(alloc.createdAt);
                  const elapsedSeconds = Math.floor((new Date() - createdAt) / 1000);
                  const remaining = Math.max(0, 1080 - elapsedSeconds);
                  alloc.timeLeft = remaining;
                  if (remaining === 0) {
                    alloc.status = 'expired';
                  }
                } else {
                  alloc.timeLeft = 0;
                }
              });
            };

            const startPolling = () => {
              stopPolling();
              fetchData();
              pollingTimer = setInterval(fetchData, 3000); 
            };

            const stopPolling = () => {
              if (pollingTimer) {
                clearInterval(pollingTimer);
                pollingTimer = null;
              }
            };

            const fetchData = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!token) {
                userLoaded.value = true;
                return;
              }

              // ১. ইউজার প্রোফাইল ডাটা
              try {
                const profileRes = await fetch('/api/v1/auth/me', {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                
                if (profileRes.status === 401) {
                  signOut();
                  userLoaded.value = true;
                  return;
                }

                const profileData = await profileRes.json();
                if (profileData.status === 'success') {
                  user.value = profileData.user;
                  profile.value = profileData.user;
                  announcement.value = profileData.announcement;
                  if (profileData.user.wallet_address && !walletAddressInput.value) {
                    walletAddressInput.value = profileData.user.wallet_address;
                  }
                }
              } catch (e) {
                console.log("Profile Fetch Error:", e);
              }

              userLoaded.value = true; 

              // ২. ওটিপি ও্যাক্টিভ নম্বর লাইভ সিঙ্ক
              if (profile.value) {
                try {
                  const allocRes = await fetch('/api/v1/user-allocations', {
                    headers: { 
                      'Authorization': `Bearer ${token}`,
                      'X-MINO-API-KEY': profile.value.api_key || ''
                    }
                  });
                  const allocData = await allocRes.json();
                  if (allocData.status === 'success') {
                    const prevCompletedCount = allocations.value.filter(a => a.status === 'completed').length;
                    
                    allocations.value = allocData.allocations;
                    updateTimers();

                    const newCompletedCount = allocations.value.filter(a => a.status === 'completed').length;
                    if (newCompletedCount > prevCompletedCount && prevCompletedCount > 0) {
                      playBeep();
                      triggerToast("নতুন ওটিপি (OTP) এসেছে! 🔔");
                    }
                  }
                } catch (e) {}
              }

              // ৩. কনসোল সিগন্যাল ডাটা
              try {
                const consoleRes = await fetch('/api/v1/live-console');
                const consoleData = await consoleRes.json();
                if (consoleData.status === 'success') {
                  liveLogs.value = consoleData.data;
                }
              } catch (e) {}

              // ৪. ড্যাশবোর্ড ওটিপি রিপোর্ট ফেচ
              if (profile.value) {
                try {
                  const otpRes = await fetch('/api/v1/success-otp?api_key=' + (profile.value.api_key || ''));
                  const otpData = await otpRes.json();
                  if (otpData.status === 'success') {
                    successOtps.value = otpData.data;
                  }
                } catch (e) {}
              }
            };

            const handleUpdateWallet = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!token || !walletAddressInput.value.trim()) return;
              
              walletLoading.value = true;
              try {
                const res = await fetch('/api/v1/user/update-wallet', {
                  method: 'POST',
                  headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                  },
                  body: JSON.stringify({ wallet_address: walletAddressInput.value })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast("ওয়ালেট এড্রেস সফলভাবে সেভ হয়েছে! ✅");
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("ওয়ালেট আপডেট করা সম্ভব হয়নি।");
              }
              walletLoading.value = false;
            };

            const handleGenerateApiKey = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!token) return;
              
              apiGenLoading.value = true;
              try {
                const res = await fetch('/api/v1/user/generate-key', {
                  method: 'POST',
                  headers: { 
                    'Authorization': `Bearer ${token}`
                  }
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast("এপিআই কি সফলভাবে জেনারেট হয়েছে! ✅");
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("এপিআই কি জেনারেট করা সম্ভব হয়নি।");
              }
              apiGenLoading.value = false;
            };

            // উইথড্র রিকোয়েস্ট সাবমিট করা
            const submitWithdrawal = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!token || withdrawAmount.value <= 0) return;
              try {
                const res = await fetch('/api/v1/user/withdraw', {
                  method: 'POST',
                  headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                  },
                  body: JSON.stringify({
                    amount: withdrawAmount.value,
                    method: withdrawMethod.value,
                    address: profile.value.wallet_address
                  })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  alert("আপনার উইথড্রয়াল রিকোয়েস্টটি পেন্ডিং লিস্টে জমা হয়েছে। এডমিন ভেরিফাই করে অ্যাপ্রুভ করবেন।");
                  withdrawAmount.value = 0;
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("রিকোয়েস্ট পাঠাতে সমস্যা হয়েছে।");
              }
            };

            // লাইভ এপিআই টেস্ট রান লজিক
            const runLiveApiTest = async () => {
              if (!profile.value?.api_key) {
                alert("প্রথমে একটি এপিআই কি জেনারেট করে নিন।");
                return;
              }
              testApiLoading.value = true;
              testApiResponse.value = null;
              try {
                const res = await fetch(`/api/v1/getnum?api_key=${profile.value.api_key}&rid=${testRange.value}`);
                const data = await res.json();
                testApiResponse.value = JSON.stringify(data, null, 2);
              } catch (e) {
                testApiResponse.value = "API Request failed.";
              }
              testApiLoading.value = false;
            };

            onMounted(() => {
              const token = localStorage.getItem('mino_session_token');
              if (token) {
                startPolling();
              } else {
                userLoaded.value = true;
              }
              setInterval(updateTimers, 1000);
            });

            const handleAuth = async () => {
              if (!authEmail.value || !authPassword.value) return;
              authLoading.value = true;
              try {
                const url = isRegistering.value ? '/api/v1/auth/register' : '/api/v1/auth/login';
                const res = await fetch(url, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ 
                    email: authEmail.value, 
                    password: authPassword.value,
                    name: authName.value
                  })
                });
                const data = await res.json();
                
                if (data.status === 'success') {
                  if (isRegistering.value) {
                     alert("আপনার অ্যাকাউন্ট সফলভাবে তৈরি হয়েছে। অনুগ্রহ করে অ্যাডমিনের অ্যাপ্রুভালের জন্য অপেক্ষা করুন।");
                     isRegistering.value = false;
                     authLoading.value = false;
                     return;
                  }
                  localStorage.setItem('mino_session_token', data.token);
                  user.value = data.user;
                  profile.value = data.user;
                  startPolling();
                } else {
                  alert(data.message);
                }
              } catch (err) {
                alert(err.message || 'Authentication failed');
              }
              authLoading.value = false;
            };

            const signOut = () => {
              localStorage.removeItem('mino_session_token');
              user.value = null;
              profile.value = null;
              activeNumber.value = null;
              otpResult.value = null;
              allocations.value = [];
              stopPolling();
            };

            const handleGetNumber = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!profile.value || !token) return;
              loadingNumber.value = true;
              otpResult.value = null;
              activeNumber.value = null;
              activeCountry.value = '';
              activeOperator.value = '';
              try {
                const natVal = nationalFormat.value ? 1 : 0;
                const remVal = removePlus.value ? 1 : 0;
                const res = await fetch(`/api/v1/getnum?rid=${rid.value}&national=${natVal}&remove_plus=${remVal}`, {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast("নম্বর সফলভাবে বরাদ্দ হয়েছে!");
                  fetchData(); 
                } else {
                  alert(data.message);
                }
              } catch (err) {
                alert('Failed to get number');
              }
              loadingNumber.value = false;
            };

            const formatTime = (seconds) => {
              const mins = Math.floor(seconds / 60);
              const secs = seconds % 60;
              return mins + ':' + (secs < 10 ? '0' : '') + secs;
            };

            const formatTimestamp = (isoString) => {
              if (!isoString) return '';
              try {
                const d = new Date(isoString);
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              } catch (e) {
                return '';
              }
            };

            // উইথড্র এমাউন্ট ভ্যালু স্টোর করার জন্য উইজেট
            const withdrawAmount = ref('');
            const withdrawMethod = ref('TRC20');

            return {
              userLoaded, user, profile, authName, authEmail, authPassword, isRegistering, authLoading,
              currentTab, announcement, rid, nationalFormat, removePlus, activeNumber, activeCountry, activeOperator, otpResult, loadingNumber, liveLogs, successOtps,
              allocations, currentPage, itemsPerPage, paginatedAllocations, totalPages, prevPage, nextPage, searchQuery,
              showToast, toastMessage, copyToClipboard, copyFullSms, walletAddressInput, walletLoading, handleUpdateWallet,
              handleAuth, signOut, handleGetNumber, formatTime, formatTimestamp,
              apiGenLoading, handleGenerateApiKey, runLiveApiTest, testRange, testApiLoading, testApiResponse, apiBaseUrl,
              withdrawAmount, withdrawMethod, submitWithdrawal
            };
          }
        }).mount('#app');
      </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype='text/html')

# =========================================================================
# গ্লোবাল অ্যাডমিন প্যানেল UI পরিবেশন (২০টি নতুন ও গুরুত্বপূর্ণ ফিচার সহ)
# =========================================================================
@app.route('/admin', methods=['GET'])
def admin_portal():
    admin_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>MINO SMS - MASTER ADMIN PANEL</title>
      <script src="https://cdn.tailwindcss.com"></script>
      <script src="https://cdnjs.cloudflare.com/ajax/libs/vue/3.3.4/vue.global.prod.min.js"></script>
      <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
      <style>
        [v-cloak] { display: none; }
      </style>
    </head>
    <body class="bg-slate-100 text-slate-700 font-sans select-none pb-12">
      
      <div id="admin-app">

        <!-- লোডিং স্ক্রিন -->
        <div v-if="loading" class="fixed inset-0 bg-slate-50 flex flex-col items-center justify-center space-y-4 z-50">
          <div class="h-12 w-12 border-4 border-rose-600 border-t-transparent rounded-full animate-spin"></div>
          <p class="text-xs font-black text-rose-600 uppercase tracking-widest animate-pulse">MINO MASTER ADMIN LOADING...</p>
        </div>

        <div v-cloak v-else>

          <!-- টোস্ট নোটিফিকেশন -->
          <div v-if="toast" class="fixed top-5 left-1/2 -translate-x-1/2 bg-slate-900 text-white font-black text-xs px-5 py-3 rounded-2xl shadow-xl z-[9999] transition animate-bounce">
            {{ toastMessage }}
          </div>

          <!-- এডমিন লগইন স্ক্রিন -->
          <div v-if="!adminToken" class="min-h-screen flex items-center justify-center p-4">
            <div class="bg-white p-8 rounded-3xl border border-slate-200 shadow-sm max-w-sm w-full space-y-6">
              <div class="text-center space-y-1">
                <span class="px-3 py-1 bg-rose-600 rounded-xl text-white font-black text-sm mx-auto shadow-sm w-max inline-block">MASTER ADMIN</span>
                <h1 class="text-xl font-black text-slate-900">MINO SMS PANEL</h1>
                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Authorized Access Only</p>
              </div>

              <form @submit.prevent="handleLogin" class="space-y-4">
                <div>
                  <label class="text-xs font-bold text-slate-500">Admin Username</label>
                  <input type="text" required v-model="username" class="w-full mt-1.5 p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-rose-600 transition" />
                </div>
                <div>
                  <label class="text-xs font-bold text-slate-500">Admin Password</label>
                  <input type="password" required v-model="password" class="w-full mt-1.5 p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-rose-600 transition" />
                </div>

                <button type="submit" :disabled="authLoading" class="w-full bg-rose-600 hover:bg-rose-700 text-white font-bold py-3.5 rounded-xl text-sm shadow-md transition disabled:bg-slate-300">
                  {{ authLoading ? 'LOGGING IN...' : 'ACCESS PORTAL' }}
                </button>
              </form>
            </div>
          </div>

          <!-- এডমিন ড্যাশবোর্ড কন্টেন্ট -->
          <div v-else class="min-h-screen flex flex-col md:flex-row">
            
            <!-- সাইডবার -->
            <aside class="w-full md:w-64 bg-slate-900 text-slate-300 flex flex-col shrink-0">
              <div class="p-6 border-b border-slate-800 flex items-center gap-3 bg-slate-950">
                <span class="px-2 py-0.5 bg-rose-600 rounded text-white font-black text-xs">ADMIN</span>
                <span class="text-md font-black text-white">MINO SMS</span>
              </div>

              <nav class="flex-1 p-4 space-y-1">
                <button @click="currentTab = 'dashboard'" :class="currentTab === 'dashboard' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-chart-line"></i> ড্যাশবোর্ড ওভারভিউ (Feature 1)
                </button>
                <button @click="currentTab = 'users'" :class="currentTab === 'users' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-users"></i> ইউজার কন্ট্রোল (Feature 2-5)
                </button>
                <button @click="currentTab = 'withdrawals'" :class="currentTab === 'withdrawals' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-money-bill-transfer"></i> উইথড্র রিকোয়েস্ট (Feature 6)
                </button>
                <button @click="currentTab = 'allocations'" :class="currentTab === 'allocations' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-mobile-screen"></i> নম্বর বরাদ্দ ট্র্যাকার (Feature 7)
                </button>
                <button @click="currentTab = 'otp-logs'" :class="currentTab === 'otp-logs' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-envelope-open-text"></i> গ্লোবাল ওটিপি রিপোর্ট (Feature 8)
                </button>
                <button @click="currentTab = 'settings'" :class="currentTab === 'settings' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-gears"></i> সিস্টেম কন্ট্রোল ও সেটিংস (Feature 9-20)
                </button>
              </nav>

              <div class="p-4 border-t border-slate-800 flex items-center justify-between bg-slate-950 text-xs font-bold">
                <span>ADMIN ACTIVE</span>
                <button @click="logOut" class="text-rose-400 hover:text-rose-600 font-black"><i class="fa-solid fa-right-from-bracket"></i> LOGOUT</button>
              </div>
            </aside>

            <!-- মেইন কন্টেন্ট -->
            <main class="flex-1 p-4 md:p-8 space-y-6 overflow-y-auto">
              
              <header class="flex justify-between items-center border-b border-slate-200 pb-4">
                <h2 class="text-md md:text-lg font-black text-slate-900 capitalize">{{ currentTab }} Management</h2>
                <div class="text-xs font-black bg-rose-100 text-rose-600 px-3 py-1.5 rounded-full shadow-sm uppercase tracking-wider">
                  Live Master Admin
                </div>
              </header>

              <!-- ==================== ট্যাব ১: ড্যাশবোর্ড ওভারভিউ (Feature 1) ==================== -->
              <div v-if="currentTab === 'dashboard'" class="space-y-6">
                <!-- Feature 1: অ্যাডভান্সড স্ট্যাটিস্টিক কার্ডস -->
                <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wide">মোট ইউজার সংখ্যা</p>
                    <h3 class="text-2xl font-black text-slate-900 mt-2">{{ stats.total_users }} জন</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between border-amber-200 bg-amber-50/20 animate-pulse">
                    <p class="text-[10px] text-amber-600 font-bold uppercase tracking-wide">পেন্ডিং ইউজার (Pending)</p>
                    <h3 class="text-2xl font-black text-amber-600 mt-2">{{ stats.pending_users }} জন</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wide">মোট বরাদ্দকৃত নম্বর</p>
                    <h3 class="text-2xl font-black text-slate-900 mt-2">{{ stats.total_allocations }} বার</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wide">সফল ওটিপি রিসিভ</p>
                    <h3 class="text-2xl font-black text-emerald-600 mt-2">{{ stats.total_otps }} টি</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border border-indigo-200 bg-indigo-50/10 shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-indigo-600 font-bold uppercase tracking-wide">উইথড্র রিকোয়েস্ট সংখ্যা</p>
                    <h3 class="text-2xl font-black text-indigo-600 mt-2">{{ stats.total_withdrawals }} টি</h3>
                  </div>
                </div>

                <!-- কুইক অ্যাকশন এবং লাইভ সিস্টেম স্ট্যাটাস -->
                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-3">
                  <h4 class="font-bold text-xs text-slate-400 uppercase tracking-widest">কুইক কন্ট্রোল কন্ট্রোল প্যানেল</h4>
                  <div class="grid md:grid-cols-2 gap-4">
                    <div class="bg-slate-50 p-4 rounded-2xl border flex items-center justify-between">
                      <div>
                        <p class="text-xs font-black text-slate-700">মেনটেইনেন্স মোড (Maintenance Mode)</p>
                        <p class="text-[10px] text-slate-400 mt-0.5">চালু করলে সাধারণ ইউজারদের প্যানেল সাময়িকভাবে বন্ধ হয়ে যাবে।</p>
                      </div>
                      <button @click="toggleMaintenanceMode" :class="stats.maintenance_mode ? 'bg-amber-600 text-white' : 'bg-slate-200 text-slate-600'" class="px-4 py-2 rounded-xl text-xs font-black transition">
                        {{ stats.maintenance_mode ? 'চলমান (ON)' : 'বন্ধ (OFF)' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ==================== ট্যাব ২: ইউজার কন্ট্রোল (Feature 2-5) ==================== -->
              <div v-if="currentTab === 'users'" class="space-y-4">
                <!-- Feature 2: ইউজার সার্চ ও অ্যাডভান্স ফিল্টারিং -->
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                  <input type="text" v-model="searchQuery" placeholder="ইউজার নাম, ইমেইল বা আইডি কোড দিয়ে খুঁজুন..." class="w-full sm:w-80 p-3 bg-white border rounded-2xl text-xs font-semibold outline-none focus:border-rose-600" />
                  
                  <!-- Feature 3: এক্সপোর্ট CSV বাটন -->
                  <button @click="exportUsersToCSV" class="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold px-4 py-2 rounded-xl transition flex items-center gap-1">
                    <i class="fa-solid fa-file-csv"></i> Export Users CSV
                  </button>
                </div>

                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">ইউজার ও আইডি কোড</th>
                          <th class="p-4">ইমেইল ও পাসওয়ার্ড</th>
                          <th class="p-4">ব্যালেন্স</th>
                          <th class="p-4">ওটিপি রেট (৳)</th>
                          <th class="p-4">স্ট্যাটাস</th>
                          <th class="p-4 text-right">অ্যাকশন</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="filteredUsers.length === 0">
                          <td colspan="6" class="p-8 text-center text-slate-400 font-bold">কোনো ইউজার খুঁজে পাওয়া যায়নি।</td>
                        </tr>
                        <!-- Feature 4: ইউজার ম্যানেজমেন্ট ও ডিটেইল টেবিল -->
                        <tr v-else v-for="u in filteredUsers" :key="u.uid" class="hover:bg-slate-50/50 transition">
                          <td class="p-4">
                            <p class="font-black text-slate-900 text-sm">{{ u.name }}</p>
                            <p class="text-[10px] text-[#0088CC] tracking-wider mt-0.5">ID: {{ u.id_code || 'MINO-N/A' }}</p>
                            <p class="text-[9px] text-slate-400 font-medium">UID: {{ u.uid }}</p>
                          </td>
                          <td class="p-4">
                            <p class="font-mono text-slate-800">{{ u.email }}</p>
                            <p class="text-[10px] text-slate-400 mt-1 font-mono">Password: {{ u.password }}</p>
                          </td>
                          <td class="p-4 font-black text-slate-900 text-sm">৳ {{ parseFloat(u.balance || 0).toFixed(2) }}</td>
                          <td class="p-4 font-black text-slate-700 text-xs">৳ {{ parseFloat(u.otp_rate || 0.40).toFixed(2) }}</td>
                          <td class="p-4">
                            <!-- Feature 5: ইউজার অনুমোদন / পেন্ডিং / ব্যান স্ট্যাটাস ট্যাগ -->
                            <span v-if="u.status === 'approved'" class="bg-emerald-100 text-emerald-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Approved</span>
                            <span v-else-if="u.status === 'pending'" class="bg-amber-100 text-amber-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Pending</span>
                            <span v-else class="bg-rose-100 text-rose-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Banned</span>
                          </td>
                          <td class="p-4 text-right space-x-1 whitespace-nowrap">
                            <button @click="openEditModal(u)" class="bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[11px] font-bold px-3 py-1.5 rounded-xl transition">এডিট</button>
                            <button @click="deleteUser(u.uid)" class="bg-rose-50 hover:bg-rose-100 text-rose-700 text-[11px] font-bold px-3 py-1.5 rounded-xl transition">ডিলেট</button>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                <!-- ইউজার এডিট মোডাল উইন্ডো (অ্যাডভান্সড ব্যালেন্স ও রেট কন্ট্রোল) -->
                <div v-if="editUser" class="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                  <div class="bg-white p-6 rounded-3xl border shadow-xl max-w-md w-full space-y-4">
                    <div class="flex justify-between items-center border-b pb-2">
                      <h3 class="font-black text-slate-900 text-sm">এডিট ইউজার: {{ editUser.name }}</h3>
                      <button @click="editUser = null" class="text-slate-400 hover:text-rose-600"><i class="fa-solid fa-xmark text-lg"></i></button>
                    </div>

                    <div class="space-y-3 text-xs font-bold">
                      <div>
                        <label class="text-slate-400">ম্যানুয়াল ব্যালেন্স এডিট (৳)</label>
                        <input type="number" step="0.01" v-model="editUser.balance" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm font-black outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">ব্যক্তিগত ওটিপি রেট (৳)</label>
                        <input type="number" step="0.01" v-model="editUser.otp_rate" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm font-black outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">ইউজার পাসওয়ার্ড রিসেট (Password Overrides)</label>
                        <input type="text" v-model="editUser.password" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">ওয়ালেট এড্রেস</label>
                        <input type="text" v-model="editUser.wallet_address" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">এপিআই কি (API KEY)</label>
                        <input type="text" v-model="editUser.api_key" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none font-mono focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">অ্যাকাউন্ট স্ট্যাটাস</label>
                        <select v-model="editUser.status" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none focus:border-rose-600">
                          <option value="approved">Approved (সক্রিয়)</option>
                          <option value="pending">Pending (অনুমোদনহীন)</option>
                          <option value="banned">Banned (ব্লকড)</option>
                        </select>
                      </div>
                    </div>

                    <div class="flex gap-2 pt-2">
                      <button @click="editUser = null" class="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-600 font-bold py-3 rounded-xl text-xs transition">বাতিল</button>
                      <button @click="saveUserChanges" class="flex-1 bg-rose-600 hover:bg-rose-700 text-white font-bold py-3 rounded-xl text-xs transition">সংরক্ষণ করুন</button>
                    </div>
                  </div>
                </div>

              </div>

              <!-- ==================== ট্যাব ৩: উইথড্র রিকোয়েস্ট (Feature 6) ==================== -->
              <div v-if="currentTab === 'withdrawals'" class="space-y-4">
                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">ইউজার ও আইডি কোড</th>
                          <th class="p-4">পরিমাণ (Amount)</th>
                          <th class="p-4">উইথড্র মেথড</th>
                          <th class="p-4">গন্তব্য ওয়ালেট এড্রেস</th>
                          <th class="p-4">স্ট্যাটাস</th>
                          <th class="p-4">সময়</th>
                          <th class="p-4 text-right">অ্যাকশন</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="withdrawals.length === 0">
                          <td colspan="7" class="p-8 text-center text-slate-400 font-bold">কোনো উইথড্র রিকোয়েস্ট জমা নেই।</td>
                        </tr>
                        <tr v-else v-for="wd in withdrawals" :key="wd.id" class="hover:bg-slate-50/50 transition">
                          <td class="p-4">
                            <p class="font-black text-slate-900 text-sm">{{ wd.userName }}</p>
                            <p class="text-[10px] text-slate-400 mt-0.5">{{ wd.userEmail }}</p>
                          </td>
                          <td class="p-4 font-black text-rose-600 text-sm">৳ {{ parseFloat(wd.amount || 0).toFixed(2) }}</td>
                          <td class="p-4 font-black text-indigo-600 uppercase">{{ wd.method }}</td>
                          <td class="p-4 font-mono select-all text-slate-800 break-all max-w-xs">{{ wd.address }}</td>
                          <td class="p-4">
                            <span v-if="wd.status === 'approved'" class="bg-emerald-100 text-emerald-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Approved</span>
                            <span v-else-if="wd.status === 'pending'" class="bg-amber-100 text-amber-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase animate-pulse">Pending</span>
                            <span v-else class="bg-rose-100 text-rose-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Rejected</span>
                          </td>
                          <td class="p-4 font-mono text-slate-400 text-[10px]">{{ formatTimestamp(wd.createdAt) }}</td>
                          <td class="p-4 text-right space-x-1 whitespace-nowrap">
                            <button v-if="wd.status === 'pending'" @click="processWithdrawal(wd.id, 'approved')" class="bg-emerald-600 hover:bg-emerald-700 text-white text-[10px] font-black px-3 py-1.5 rounded-xl transition">Approve</button>
                            <button v-if="wd.status === 'pending'" @click="processWithdrawal(wd.id, 'rejected')" class="bg-rose-600 hover:bg-rose-700 text-white text-[10px] font-black px-3 py-1.5 rounded-xl transition">Reject</button>
                            <span v-else class="text-slate-400 italic">সম্পন্ন</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <!-- ==================== ট্যাব ৪: নম্বর বরাদ্দ ট্র্যাকার (Feature 7) ==================== -->
              <div v-if="currentTab === 'allocations'" class="space-y-4">
                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">ইউজার আইডি</th>
                          <th class="p-4">নম্বর</th>
                          <th class="p-4">রেঞ্জ (Range)</th>
                          <th class="p-4">দেশ ও অপারেটর</th>
                          <th class="p-4">স্ট্যাটাস</th>
                          <th class="p-4">সময়</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="allocations.length === 0">
                          <td colspan="6" class="p-8 text-center text-slate-400 font-bold">কোনো নম্বর বরাদ্দ ডাটা নেই।</td>
                        </tr>
                        <tr v-else v-for="a in allocations" :key="a.id">
                          <td class="p-4">
                            <span class="font-mono bg-slate-100 px-2 py-0.5 rounded">{{ a.userId }}</span>
                          </td>
                          <td class="p-4 font-black text-slate-900 text-sm">{{ a.number }}</td>
                          <td class="p-4 font-mono font-bold text-[#0088CC]">{{ a.rid }}</td>
                          <td class="p-4">
                            <p class="font-bold text-slate-800">{{ a.country }}</p>
                            <p class="text-[10px] text-slate-400 mt-0.5 uppercase">{{ a.operator }}</p>
                          </td>
                          <td class="p-4">
                            <span v-if="a.status === 'active'" class="bg-amber-100 text-amber-800 text-[9px] font-black px-2 py-0.5 rounded uppercase">ACTIVE</span>
                            <span v-else-if="a.status === 'completed'" class="bg-emerald-100 text-emerald-800 text-[9px] font-black px-2 py-0.5 rounded uppercase">SUCCESS</span>
                            <span v-else class="bg-slate-100 text-slate-500 text-[9px] font-black px-2 py-0.5 rounded uppercase">EXPIRED</span>
                          </td>
                          <td class="p-4 font-mono text-slate-400 text-[10px]">{{ formatTimestamp(a.createdAt) }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <!-- ==================== ট্যাব ৫: গ্লোবাল ওটিপি রিপোর্ট (Feature 8) ==================== -->
              <div v-if="currentTab === 'otp-logs'" class="space-y-4">
                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">ইউজার আইডি</th>
                          <th class="p-4">নম্বর</th>
                          <th class="p-4">সার্ভিস</th>
                          <th class="p-4">ওটিপি কোড</th>
                          <th class="p-4">সম্পূর্ণ মেসেজ</th>
                          <th class="p-4">রেভিনিউ</th>
                          <th class="p-4">সময়</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="otpLogs.length === 0">
                          <td colspan="7" class="p-8 text-center text-slate-400 font-bold">কোনো ওটিপি ডাটা নেই।</td>
                        </tr>
                        <tr v-else v-for="log in otpLogs" :key="log.createdAt">
                          <td class="p-4">
                            <span class="font-mono bg-slate-100 px-2 py-0.5 rounded">{{ log.userId }}</span>
                          </td>
                          <td class="p-4 font-black text-slate-900">{{ log.number }}</td>
                          <td class="p-4 uppercase text-[#0088CC] font-black text-[10px]">{{ log.service }}</td>
                          <td class="p-4 font-black text-emerald-600 text-sm">{{ log.otpCode }}</td>
                          <td class="p-4 text-slate-500 leading-relaxed max-w-xs truncate" :title="log.message">{{ log.message }}</td>
                          <td class="p-4 font-black text-slate-900">৳ {{ parseFloat(log.revenue || 0).toFixed(2) }}</td>
                          <td class="p-4 font-mono text-slate-400 text-[10px]">{{ formatTimestamp(log.createdAt) }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <!-- ==================== ট্যাব ৬: সিস্টেম কন্ট্রোল ও সেটিংস (Feature 9-20) ==================== -->
              <div v-if="currentTab === 'settings'" class="space-y-6">
                
                <!-- Feature 9: অ্যানাউন্সমেন্ট ব্যানার আপডেট -->
                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-400 uppercase tracking-widest flex items-center gap-2">
                    <i class="fa-solid fa-bullhorn text-rose-600"></i> গ্লোবাল অ্যানাউন্সমেন্ট কন্ট্রোল (Announcement Banner)
                  </h3>
                  <textarea v-model="announcementInput" rows="2" placeholder="ইউজার প্যানেলে দেখানোর জন্য নোটিশ বা অফার লিখুন..." class="w-full p-3 bg-slate-50 border rounded-xl text-xs outline-none focus:border-rose-600 font-semibold"></textarea>
                  <button @click="updateAnnouncement" class="bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold px-4 py-2.5 rounded-xl transition">
                    ঘোষণা আপডেট করুন
                  </button>
                </div>

                <!-- Feature 10-20: ব্যাকআপ এবং ডেভেলপমেন্ট সেটিংস -->
                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-400 uppercase tracking-widest flex items-center gap-2">
                    <i class="fa-solid fa-database text-rose-600"></i> এডভান্সড ডেটাবেজ ব্যাকআপ ও সিকিউরিটি
                  </h3>
                  
                  <div class="grid md:grid-cols-2 gap-4 text-xs font-semibold">
                    <div class="bg-slate-50 p-4 rounded-xl border flex flex-col justify-between">
                      <div>
                        <p class="font-black text-slate-800">ডেটাবেজ ওয়ান-ক্লিক ব্যাকআপ (JSON)</p>
                        <p class="text-[10px] text-slate-400 mt-1">ফায়ারবেজ ডেটাবেজের সম্পূর্ণ ডাটা এক ক্লিকে ডাউনলোড করুন।</p>
                      </div>
                      <button @click="downloadBackup" class="w-max mt-3 bg-rose-600 hover:bg-rose-700 text-white font-bold px-4 py-2 rounded-xl transition">
                        ডাউনলোড ব্যাকআপ ফাইল (JSON)
                      </button>
                    </div>

                    <div class="bg-slate-50 p-4 rounded-xl border">
                      <p class="font-black text-slate-800">সিস্টেম সিকিউরিটি এবং এপিআই মনিটর</p>
                      <ul class="text-[10px] text-slate-500 mt-2 list-disc list-inside space-y-1">
                        <li><strong>Feature 11:</strong> IP and Location Log tracking on database.</li>
                        <li><strong>Feature 12:</strong> Default User Sign-Up State holds in Pending.</li>
                        <li><strong>Feature 13:</strong> Realtime STEX endpoint fallback routing configuration active.</li>
                        <li><strong>Feature 14:</strong> Elite/Custom OTP billing configurations per User.</li>
                        <li><strong>Feature 15:</strong> Password override control on database nodes.</li>
                        <li><strong>Feature 16:</strong> Automatic database backup generator mapping.</li>
                        <li><strong>Feature 17:</strong> Global maintenance routing switch active.</li>
                        <li><strong>Feature 18:</strong> Live signal intercept radar filter mapped.</li>
                        <li><strong>Feature 19:</strong> Safe environment credential string decoding.</li>
                        <li><strong>Feature 20:</strong> Dynamic 18-minute number expiry timers synced.</li>
                      </ul>
                    </div>
                  </div>
                </div>

              </div>

            </main>
          </div>
        </div>

      </div>

      <script>
        const { createApp, ref, onMounted, computed } = Vue;

        createApp({
          setup() {
            const loading = ref(true);
            const authLoading = ref(false);
            const adminToken = ref(localStorage.getItem('mino_admin_token') || '');
            const username = ref('');
            const password = ref('');
            const currentTab = ref('dashboard');
            const searchQuery = ref('');

            const announcementInput = ref('');

            const stats = ref({
              total_users: 0,
              pending_users: 0,
              total_allocations: 0,
              total_otps: 0,
              total_withdrawals: 0,
              maintenance_mode: false
            });

            const users = ref([]);
            const allocations = ref([]);
            const otpLogs = ref([]);
            const withdrawals = ref([]);
            const editUser = ref(null);

            const toast = ref(false);
            const toastMessage = ref('');

            const triggerToast = (msg) => {
              toastMessage.value = msg;
              toast.value = true;
              setTimeout(() => { toast.value = false; }, 2000);
            };

            const handleLogin = async () => {
              if (!username.value || !password.value) return;
              authLoading.value = true;
              try {
                const res = await fetch('/api/v1/admin/login', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ username: username.value, password: password.value })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  adminToken.value = data.token;
                  localStorage.setItem('mino_admin_token', data.token);
                  triggerToast("মাস্টার পোর্টাল অ্যাক্সেস গ্রান্টেড! 🔓");
                  fetchDashboardData();
                } else {
                  alert(data.message || 'ভুল ইউজারনেম বা পাসওয়ার্ড।');
                }
              } catch (e) {
                alert("সার্ভার কানেকশন ত্রুটি।");
              }
              authLoading.value = false;
            };

            const logOut = () => {
              localStorage.removeItem('mino_admin_token');
              adminToken.value = '';
              triggerToast("সফলভাবে লগআউট করা হয়েছে। 🔒");
            };

            const fetchDashboardData = async () => {
              if (!adminToken.value) {
                loading.value = false;
                return;
              }
              try {
                // ১. স্ট্যাটস ফেচ
                const statRes = await fetch('/api/v1/admin/dashboard', {
                  headers: { 'Authorization': `Bearer ${adminToken.value}` }
                });
                if (statRes.status === 401) { logOut(); return; }
                const statData = await statRes.json();
                if (statData.status === 'success') stats.value = statData.stats;

                // ২. ইউজার ফেচ
                const userRes = await fetch('/api/v1/admin/users', {
                  headers: { 'Authorization': `Bearer ${adminToken.value}` }
                });
                const userData = await userRes.json();
                if (userData.status === 'success') users.value = userData.users;

                // ৩. নম্বর রিকোয়েস্ট ট্র্যাকার ফেচ
                const allocRes = await fetch('/api/v1/admin/allocations', {
                  headers: { 'Authorization': `Bearer ${adminToken.value}` }
                });
                const allocData = await allocRes.json();
                if (allocData.status === 'success') allocations.value = allocData.allocations;

                // ৪. গ্লোবাল ওটিপি ফেচ
                const logRes = await fetch('/api/v1/admin/otp-logs', {
                  headers: { 'Authorization': `Bearer ${adminToken.value}` }
                });
                const logData = await logRes.json();
                if (logData.status === 'success') otpLogs.value = logData.otp_logs;

                // ৫. উইথড্রয়াল ফেচ
                const wdRes = await fetch('/api/v1/admin/withdrawals', {
                  headers: { 'Authorization': `Bearer ${adminToken.value}` }
                });
                const wdData = await wdRes.json();
                if (wdData.status === 'success') withdrawals.value = wdData.withdrawals;

              } catch (e) {
                console.log("Admin API error:", e);
              }
              loading.value = false;
            };

            const toggleMaintenanceMode = async () => {
              const currentMode = stats.value.maintenance_mode;
              try {
                const res = await fetch('/api/v1/admin/settings/toggle-maintenance', {
                  method: 'POST',
                  headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${adminToken.value}`
                  },
                  body: JSON.stringify({ maintenance_mode: !currentMode })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  stats.value.maintenance_mode = data.maintenance_mode;
                  triggerToast(`মেনটেইনেন্স মোড ${data.maintenance_mode ? 'চালু' : 'বন্ধ'} করা হয়েছে। 🛠️`);
                }
              } catch (e) {}
            };

            const updateAnnouncement = async () => {
              try {
                const res = await fetch('/api/v1/admin/announcement', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${adminToken.value}`
                  },
                  body: JSON.stringify({ announcement: announcementInput.value })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast("গ্লোবাল অ্যানাউন্সমেন্ট আপডেট করা হয়েছে! 📢");
                }
              } catch (e) {}
            };

            const processWithdrawal = async (id, action) => {
              if (!confirm(`আপনি কি এই উইথড্র রিকোয়েস্টটি ${action} করতে চান?`)) return;
              try {
                const res = await fetch('/api/v1/admin/withdrawals/action', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${adminToken.value}`
                  },
                  body: JSON.stringify({ id, action })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast(`Withdrawal request has been ${action}.`);
                  fetchDashboardData();
                } else {
                  alert(data.message);
                }
              } catch (e) {}
            };

            const downloadBackup = async () => {
              try {
                const res = await fetch('/api/v1/admin/backup', {
                  headers: { 'Authorization': `Bearer ${adminToken.value}` }
                });
                const data = await res.json();
                if (data.status === 'success') {
                  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(data.data, null, 2));
                  const downloadAnchor = document.createElement('a');
                  downloadAnchor.setAttribute("href", dataStr);
                  downloadAnchor.setAttribute("download", `mino_backup_${new Date().toISOString().slice(0,10)}.json`);
                  document.body.appendChild(downloadAnchor);
                  downloadAnchor.click();
                  downloadAnchor.remove();
                  triggerToast("ডেটাবেজ ব্যাকআপ ফাইল তৈরি সম্পন্ন হয়েছে! 📥");
                }
              } catch (e) {}
            };

            const exportUsersToCSV = () => {
              let csvContent = "data:text/csv;charset=utf-8,";
              csvContent += "Name,Email,Balance,Status,OTP Rate\\n";
              
              users.value.forEach(u => {
                csvContent += `"${u.name}","${u.email}",${u.balance},"${u.status}",${u.otp_rate}\\n`;
              });

              const encodedUri = encodeURI(csvContent);
              const link = document.createElement("a");
              link.setAttribute("href", encodedUri);
              link.setAttribute("download", `mino_users_export_${new Date().toISOString().slice(0,10)}.csv`);
              document.body.appendChild(link);
              link.click();
              link.remove();
              triggerToast("ইউজার লিস্ট CSV ফাইল ডাউনলোড সম্পন্ন হয়েছে! 📊");
            };

            const filteredUsers = computed(() => {
              if (!users.value) return [];
              const q = searchQuery.value.toLowerCase().trim();
              if (!q) return users.value;
              return users.value.filter(u => 
                (u.name && u.name.toLowerCase().includes(q)) || 
                (u.email && u.email.toLowerCase().includes(q)) ||
                (u.id_code && u.id_code.toLowerCase().includes(q))
              );
            });

            const openEditModal = (u) => {
              editUser.value = { ...u };
            };

            const saveUserChanges = async () => {
              if (!editUser.value) return;
              try {
                const res = await fetch('/api/v1/admin/users/update', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${adminToken.value}`
                  },
                  body: JSON.stringify(editUser.value)
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast("ইউজার তথ্য সফলভাবে আপডেট করা হয়েছে! ✅");
                  editUser.value = null;
                  fetchDashboardData();
                } else {
                  alert(data.message);
                }
              } catch (e) {}
            };

            const deleteUser = async (uid) => {
              if (!confirm("আপনি কি নিশ্চিতভাবে এই ইউজার অ্যাকাউন্টটি মুছে ফেলতে চান?")) return;
              try {
                const res = await fetch('/api/v1/admin/users/delete', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${adminToken.value}`
                  },
                  body: JSON.stringify({ uid })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast("ইউজার সফলভাবে ডিলেট করা হয়েছে। 🗑️");
                  fetchDashboardData();
                }
              } catch (e) {}
            };

            const formatTimestamp = (isoString) => {
              if (!isoString) return '';
              try {
                const d = new Date(isoString);
                return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              } catch (e) {
                return '';
              }
            };

            onMounted(() => {
              fetchDashboardData();
              setInterval(fetchDashboardData, 10000); 
            });

            return {
              loading, authLoading, adminToken, username, password, currentTab, searchQuery,
              stats, users, allocations, otpLogs, withdrawals, editUser, toast, toastMessage, announcementInput,
              handleLogin, logOut, toggleMaintenanceMode, updateAnnouncement, processWithdrawal, downloadBackup, exportUsersToCSV,
              filteredUsers, openEditModal, saveUserChanges, deleteUser, formatTimestamp
            };
          }
        }).mount('#admin-app');
      </script>
    </body>
    </html>
    """
    return Response(admin_html, mimetype='text/html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 4000))
    app.run(host='0.0.0.0', port=port)