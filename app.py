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
# Firebase Admin Configuration
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

# Firebase app initialization
if not firebase_admin._apps and CRED_DICT.get("private_key"):
    CRED_DICT["private_key"] = CRED_DICT["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(CRED_DICT)
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })
elif not firebase_admin._apps:
    print("Warning: Firebase Credentials could not be loaded because FIREBASE_PRIVATE_KEY is missing.")

# =========================================================================
# Admin Credentials and Authentication Helpers
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

# Maintenance mode checker function
def is_maintenance():
    try:
        val = fb_db.reference('/settings/maintenance_mode').get()
        return bool(val)
    except Exception:
        return False

# =========================================================================
# Before Request (CORS and Maintenance Mode)
# =========================================================================
@app.before_request
def handle_pre_requests():
    if request.method == 'OPTIONS':
        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-MINO-API-KEY,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        return response

    if not request.path.startswith('/admin') and not request.path.startswith('/api/') and not request.path.startswith('/@public/api/'):
        pass
    else:
        if is_maintenance() and not request.path.startswith('/admin') and not request.path.startswith('/api/v1/admin'):
            return jsonify({'status': 'error', 'message': 'System is under maintenance'}), 503

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
# Database Handlers (Optimized for safe indexing and maximum queries speed)
# =========================================================================
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

# Highly Optimized Authentication Middleware (Query-by-field, fallback to scan on missing rule)
def get_current_user_optimized():
    # 1. Bearer Token Check
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        user_ref = fb_db.reference(f'/users/{token}')
        user = user_ref.get()
        if user and user.get('status', 'pending') == 'approved':
            return user

    # 2. API Key Check (Header or Parameter or Payload)
    api_key = request.headers.get('X-MINO-API-KEY') or request.args.get('api_key')
    if not api_key and request.is_json:
        try:
            api_key = request.json.get('api_key')
        except Exception:
            pass
            
    if api_key:
        users_ref = fb_db.reference('/users')
        try:
            query = users_ref.order_by_child('api_key').equal_to(api_key).get()
            if query and isinstance(query, dict):
                for u_data in query.values():
                    if u_data.get('status', 'pending') == 'approved':
                        return u_data
        except Exception:
            # Fallback in-memory scanner in case indexes fail
            all_users = users_ref.get() or {}
            if isinstance(all_users, dict):
                for u_data in all_users.values():
                    if u_data.get('api_key') == api_key and u_data.get('status', 'pending') == 'approved':
                        return u_data
    return None

# =========================================================================
# User Registration & Authorization APIs
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

        # Check existing email using memory fallback safe lookup
        users_ref = fb_db.reference('/users')
        all_users = users_ref.get() or {}
        if isinstance(all_users, dict):
            for u in all_users.values():
                if u.get('email') == email:
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

        users_ref = fb_db.reference('/users')
        all_users = users_ref.get() or {}
        if isinstance(all_users, dict):
            for uid, u in all_users.items():
                if u.get('email') == email and u.get('password') == password:
                    status = u.get('status', 'pending')
                    if status == 'pending':
                        return jsonify({'status': 'error', 'message': 'Your account is pending administrator approval.'}), 403
                    if status == 'banned':
                        return jsonify({'status': 'error', 'message': 'Your account has been banned.'}), 403
                    
                    return jsonify({'status': 'success', 'token': uid, 'user': u})

        return jsonify({'status': 'error', 'message': 'Incorrect email or password.'}), 401
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/auth/me', methods=['GET'])
def get_me():
    try:
        u = get_current_user_optimized()
        if not u:
            return jsonify({'status': 'error', 'message': 'Unauthorized or Pending Approval'}), 402
        
        # Fetch global announcement banner
        announcement = fb_db.reference('/settings/announcement').get() or ''
        return jsonify({'status': 'success', 'user': u, 'announcement': announcement})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/user/generate-key', methods=['POST'])
def generate_api_key():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402
        
        user_id = user['uid']
        if not user.get('api_key'):
            unique_key = 'mino_live_' + secrets.token_hex(16)
            fb_db.reference(f'/users/{user_id}/api_key').set(unique_key)
            return jsonify({'status': 'success', 'message': 'API Key generated', 'api_key': unique_key})
        else:
            return jsonify({'status': 'success', 'message': 'API Key already exists', 'api_key': user['api_key']})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/user/update-wallet', methods=['POST'])
def update_wallet():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402
        
        data = request.json or {}
        wallet_address = data.get('wallet_address', '').strip()
        
        user_id = user['uid']
        fb_db.reference(f'/users/{user_id}/wallet_address').set(wallet_address)
        
        return jsonify({'status': 'success', 'message': 'Wallet updated successfully', 'wallet_address': wallet_address})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/user/withdraw', methods=['POST'])
def request_withdrawal():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402
        
        data = request.json or {}
        amount = float(data.get('amount', 0))
        method = data.get('method', 'TRC20').strip()
        address = data.get('address', '').strip()
        
        if amount <= 0:
            return jsonify({'status': 'error', 'message': 'Please enter a valid withdrawal amount.'}), 400
        if amount > float(user.get('balance', 0)):
            return jsonify({'status': 'error', 'message': 'Insufficient wallet balance.'}), 400
        if not address:
            return jsonify({'status': 'error', 'message': 'A withdrawal destination address is required.'}), 400
        
        user_id = user['uid']
        new_balance = float(user.get('balance', 0)) - amount
        
        # Deduct from user balance
        fb_db.reference(f'/users/{user_id}/balance').set(new_balance)
        
        # Store withdrawal request log
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
        
        return jsonify({'status': 'success', 'message': 'Withdrawal request submitted successfully.', 'new_balance': new_balance})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# Standardized Public API Mappings (GET & POST Supported - Returns 402 on Error)
# =========================================================================

# 1. Number Booking API
@app.route('/@public/api/getnum', methods=['GET', 'POST'])
@app.route('/api/v1/getnum', methods=['GET', 'POST'])
def getnum():
    try:
        if request.method == 'POST':
            data = request.json or request.form or {}
            rid = data.get('rid')
            national = data.get('national', '1')
            remove_plus = data.get('remove_plus', '1')
        else:
            rid = request.args.get('rid')
            national = request.args.get('national', '1')
            remove_plus = request.args.get('remove_plus', '1')

        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key or Unauthorized'}), 402

        if not rid:
            return jsonify({'status': 'error', 'message': 'Range ID missing'}), 400

        clean_rid = str(rid).upper().replace('X', '').strip()
        user_id = user['uid']
        stex_data = None
        last_error = "No number available on this range"

        # external query
        try:
            params = {'rid': clean_rid, 'national': int(national), 'remove_plus': int(remove_plus)}
            res = requests.get(f"{STEX_BASE_URL}/getnum", params=params, headers={'mauthapi': STEX_API_KEY}, timeout=4)
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
                res = requests.post(f"{STEX_BASE_URL}/getnum", json=payload, headers={'mauthapi': STEX_API_KEY}, timeout=4)
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

# 2. Live Access Status API
@app.route('/@public/api/liveaccess', methods=['GET', 'POST'])
def liveaccess():
    user = get_current_user_optimized()
    if not user:
        return jsonify({'status': 'error', 'message': 'Access Denied. Invalid or Missing API credentials.'}), 402
    return jsonify({
        'status': 'success',
        'message': 'API credentials validated successfully',
        'client': {
            'uid': user.get('uid'),
            'name': user.get('name'),
            'id_code': user.get('id_code'),
            'balance': user.get('balance', 0.0),
            'otp_rate': user.get('otp_rate', 0.40)
        }
    })

# 3. Successful OTP Reports API (Index-free query processing)
@app.route('/@public/api/success-otp', methods=['GET', 'POST'])
@app.route('/api/v1/success-otp', methods=['GET', 'POST'])
def success_otp():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402

        # Fetch and filter in-memory to prevent rules errors
        all_logs_dict = fb_db.reference('/otp_logs').get() or {}
        all_logs_list = firebase_to_list(all_logs_dict)
        user_logs = [log for log in all_logs_list if log.get('userId') == user['uid']]
        user_logs.sort(key=lambda x: x.get('createdAt', ''), reverse=True)

        data = []
        for d in user_logs[:20]:
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

# 4. Live Console API
@app.route('/@public/api/console', methods=['GET', 'POST'])
@app.route('/api/v1/live-console', methods=['GET', 'POST'])
def get_live_console():
    try:
        res = requests.get(f"{STEX_BASE_URL}/console", headers={'mauthapi': STEX_API_KEY}, timeout=4)
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

# User allocations list syncing logic
@app.route('/api/v1/user-allocations', methods=['GET'])
def get_user_allocations():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402

        user_id = user['uid']
        otp_rate = float(user.get('otp_rate', 0.40))

        # Query and index fallback in memory
        all_allocs_dict = fb_db.reference('/allocated_numbers').get() or {}
        all_allocs_list = firebase_to_list(all_allocs_dict)
        active_allocs_list = [alloc for alloc in all_allocs_list if alloc.get('userId') == user_id]

        # Sync active elements with gateway
        try:
            res = requests.get(f"{STEX_BASE_URL}/success-otp", headers={'mauthapi': STEX_API_KEY}, timeout=4)
            if res.status_code == 200:
                json_data = res.json()
                meta = json_data.get('meta', {})
                if meta.get('status') == 'ok' or meta.get('code') == 200:
                    otps = json_data.get('data', {}).get('otps', [])
                    for otp_item in otps:
                        otp_num = str(otp_item.get('number', '')).replace('+', '').strip()
                        
                        for alloc in active_allocs_list:
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

                                logs_ref = fb_db.reference('/otp_logs')
                                all_logs = logs_ref.get() or {}
                                exist_log = False
                                for item in firebase_to_list(all_logs):
                                    if item.get('number') == alloc['number']:
                                        exist_log = True
                                        break
                                
                                if not exist_log:
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

        # check expired
        now = datetime.datetime.now(datetime.timezone.utc)
        for alloc in active_allocs_list:
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

        # retrieve updated view list
        refreshed_query = fb_db.reference('/allocated_numbers').get() or {}
        refreshed_list = [a for a in firebase_to_list(refreshed_query) if a.get('userId') == user_id]
        refreshed_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)

        return jsonify({'status': 'success', 'allocations': refreshed_list})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Handler for undefined APIs (Returns 402 on missing route)
@app.errorhandler(404)
def resource_not_found(e):
    if request.path.startswith('/@public/api/') or request.path.startswith('/api/'):
        return jsonify({'status': 'error', 'message': 'API endpoint does not exist. Check route definition.'}), 402
    return "Page Not Found", 404

# =========================================================================
# API Routes for Admin
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
        total_users = len(fb_db.reference('/users').get() or {})
        
        pending_users = 0
        all_users = fb_db.reference('/users').get() or {}
        if isinstance(all_users, dict):
            pending_users = sum(1 for u in all_users.values() if u.get('status') == 'pending')

        total_allocations = len(fb_db.reference('/allocated_numbers').get() or {})
        total_otps = len(fb_db.reference('/otp_logs').get() or {})
        total_withdrawals = len(fb_db.reference('/withdrawals').get() or {})
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
        users_dict = fb_db.reference('/users').get() or {}
        users_list = firebase_to_list(users_dict)
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
        withdrawals_dict = fb_db.reference('/withdrawals').get() or {}
        withdrawals_list = firebase_to_list(withdrawals_dict)
        withdrawals_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return jsonify({'status': 'success', 'withdrawals': withdrawals_list})
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
        data = fb_db.reference('/').get()
        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/allocations', methods=['GET'])
def admin_api_allocations():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        allocs_dict = fb_db.reference('/allocated_numbers').get() or {}
        allocs_list = firebase_to_list(allocs_dict)
        allocs_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return jsonify({'status': 'success', 'allocations': allocs_list})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/otp-logs', methods=['GET'])
def admin_api_otp_logs():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        logs_dict = fb_db.reference('/otp_logs').get() or {}
        logs_list = firebase_to_list(logs_dict)
        logs_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        return jsonify({'status': 'success', 'otp_logs': logs_list})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# Client-side UI Rendering (With Single Line Columns and Light Menu Drawer)
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
    <body class="text-slate-700 font-sans select-none pb-4 md:pb-0">
      
      <div id="app">

        <!-- Loading Screen Overlay -->
        <div v-if="!userLoaded" class="fixed inset-0 bg-slate-50 flex flex-col items-center justify-center space-y-4 z-[99999]">
          <div class="h-12 w-12 border-4 border-[#0088CC] border-t-transparent rounded-full animate-spin"></div>
          <p class="text-xs font-black text-[#0088CC] uppercase tracking-widest animate-pulse">MINO PANEL LOADING...</p>
        </div>

        <div v-cloak v-if="userLoaded">

          <!-- Copy Toast Notification -->
          <div v-if="showToast" class="fixed top-5 left-1/2 -translate-x-1/2 bg-[#0088CC] text-white font-black text-xs px-5 py-3.5 rounded-2xl shadow-xl z-[9999] transition animate-bounce">
            {{ toastMessage }}
          </div>

          <!-- Auth screen (Login / Register) -->
          <div v-if="!user" class="min-h-screen flex items-center justify-center p-4">
            <div class="bg-white p-6 sm:p-8 rounded-3xl border border-slate-200 shadow-sm max-w-md w-full space-y-6">
              <div class="text-center space-y-2">
                <span class="px-3 py-1.5 bg-[#0088CC] rounded-2xl flex items-center justify-center text-white font-black text-lg mx-auto shadow-md w-max">MINO</span>
                <h1 class="text-xl font-black text-slate-900">MINO SMS PANEL</h1>
                <p class="text-[10px] font-semibold text-[#0088CC] uppercase tracking-widest">{{ isRegistering ? 'Register Account' : 'Sign in to network' }}</p>
              </div>

              <form @submit.prevent="handleAuth" class="space-y-4">
                <div v-if="isRegistering">
                  <label class="text-xs font-bold text-slate-500">Your Name</label>
                  <input type="text" required v-model="authName" placeholder="Name" class="w-full mt-1.5 p-3.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-[#0088CC] transition" />
                </div>
                <div>
                  <label class="text-xs font-bold text-slate-500">Email Address</label>
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

          <!-- Main Panel Dashboard Interface -->
          <div v-else class="min-h-screen flex flex-col md:flex-row">
            
            <!-- Desktop Sidebar Navigation -->
            <aside class="hidden md:flex w-64 bg-white border-r border-slate-200 flex-col shrink-0">
              <div class="p-6 border-b border-slate-100 flex items-center gap-3">
                <span class="px-2 py-1 bg-[#0088CC] rounded-lg flex items-center justify-center text-white font-black text-sm">MINO</span>
                <span class="text-lg font-black text-slate-950">MINO SMS</span>
              </div>

              <nav class="flex-1 p-4 space-y-1">
                <button @click="currentTab = 'dashboard'" :class="currentTab === 'dashboard' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-house"></i> Dashboard
                </button>
                <button @click="currentTab = 'get-number'" :class="currentTab === 'get-number' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-mobile-screen"></i> Get Number
                </button>
                <button @click="currentTab = 'console'" :class="currentTab === 'console' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-terminal"></i> Radar Console
                </button>
                <button @click="currentTab = 'payment'" :class="currentTab === 'payment' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-wallet"></i> Payment & Withdraw
                </button>
                <button @click="currentTab = 'profile'" :class="currentTab === 'profile' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-user"></i> Profile Details
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

            <!-- Light Theme Slide-out Mobile Menu Drawer (Light Mode UI) -->
            <transition enter-active-class="transition ease-out duration-300" enter-from-class="-translate-x-full" enter-to-class="translate-x-0" leave-active-class="transition ease-in duration-200" leave-from-class="translate-x-0" leave-to-class="-translate-x-full">
              <aside v-if="mobileMenuOpen" class="fixed inset-y-0 left-0 w-64 bg-white text-slate-700 flex flex-col z-50 md:hidden shadow-2xl border-r border-slate-100">
                <div class="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50">
                  <div class="flex items-center gap-3">
                    <span class="px-2 py-1 bg-[#0088CC] rounded flex items-center justify-center text-white font-black text-xs">MINO</span>
                    <span class="text-md font-black text-slate-900">MINO SMS</span>
                  </div>
                  <button @click="mobileMenuOpen = false" class="text-slate-400 hover:text-slate-800"><i class="fa-solid fa-xmark text-lg"></i></button>
                </div>

                <nav class="flex-1 p-4 space-y-1 bg-white">
                  <button @click="navigateMobile('dashboard')" :class="currentTab === 'dashboard' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-house"></i> Dashboard
                  </button>
                  <button @click="navigateMobile('get-number')" :class="currentTab === 'get-number' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-mobile-screen"></i> Get Number
                  </button>
                  <button @click="navigateMobile('console')" :class="currentTab === 'console' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-terminal"></i> Radar Console
                  </button>
                  <button @click="navigateMobile('payment')" :class="currentTab === 'payment' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-wallet"></i> Payment & Withdraw
                  </button>
                  <button @click="navigateMobile('profile')" :class="currentTab === 'profile' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-user"></i> Profile Details
                  </button>
                </nav>

                <div class="p-4 border-t border-slate-100 bg-slate-50 text-xs font-bold flex items-center justify-between">
                  <span class="text-slate-800">{{ user?.name || 'User' }}</span>
                  <button @click="signOut" class="text-rose-500 hover:text-rose-700"><i class="fa-solid fa-right-from-bracket"></i> LOGOUT</button>
                </div>
              </aside>
            </transition>
            
            <!-- Mobile Menu Backdrop -->
            <div v-if="mobileMenuOpen" @click="mobileMenuOpen = false" class="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 md:hidden"></div>

            <!-- Main Content Area -->
            <main class="flex-1 p-4 md:p-8 space-y-6 overflow-y-auto">
              
              <header class="flex justify-between items-center border-b border-slate-200 pb-4">
                <div class="flex items-center gap-3">
                  <!-- Top Burger Menu Icon (Light Theme UI Button) -->
                  <button @click="mobileMenuOpen = true" class="md:hidden text-slate-700 bg-slate-100 hover:bg-slate-200 p-2.5 rounded-xl transition focus:outline-none">
                    <i class="fa-solid fa-bars text-lg"></i>
                  </button>
                  <span class="h-2.5 w-2.5 bg-[#0088CC] rounded-full hidden md:inline-block"></span>
                  <h2 class="text-md md:text-lg font-black text-slate-900 capitalize">{{ currentTab.replace('-', ' ') }}</h2>
                </div>
                <div class="flex items-center gap-2">
                  <span class="bg-[#0088CC] text-white text-[10px] md:text-xs font-bold px-3 py-1.5 rounded-full shadow-sm">{{ user?.name || 'User' }}</span>
                  <button @click="signOut" class="hidden md:block text-slate-400 hover:text-rose-600 p-2"><i class="fa-solid fa-right-from-bracket text-lg"></i></button>
                </div>
              </header>

              <!-- Global Announcement Banner -->
              <div v-if="announcement" class="bg-indigo-50 border border-indigo-200 text-indigo-800 px-5 py-3 rounded-2xl text-xs font-bold flex items-center gap-2 animate-pulse">
                <i class="fa-solid fa-bullhorn text-[#0088CC]"></i>
                <span>{{ announcement }}</span>
              </div>

              <!-- ==================== SECTION 1: Dashboard ==================== -->
              <div v-if="currentTab === 'dashboard'" class="space-y-6">
                <div>
                  <h3 class="text-[10px] md:text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">WALLET & REPORT</h3>
                  <div class="grid grid-cols-2 md:grid-cols-3 gap-3 md:gap-4">
                    
                    <div class="bg-white p-4 md:p-5 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-start md:items-center gap-3">
                      <div class="bg-emerald-50 h-10 w-10 rounded-xl flex items-center justify-center text-emerald-600 shrink-0"><i class="fa-solid fa-wallet text-md"></i></div>
                      <div>
                        <p class="text-[10px] text-slate-400 font-bold">Balance</p>
                        <h4 class="text-sm md:text-lg font-bold text-slate-900 mt-0.5">৳ {{ parseFloat(profile ? profile.balance : 0).toFixed(2) }}</h4>
                      </div>
                    </div>

                    <div class="bg-white p-4 md:p-5 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-start md:items-center gap-3">
                      <div class="bg-amber-50 h-10 w-10 rounded-xl flex items-center justify-center text-amber-600 shrink-0"><i class="fa-solid fa-tag text-md"></i></div>
                      <div>
                        <p class="text-[10px] text-slate-400 font-bold">OTP Rate</p>
                        <h4 class="text-sm md:text-lg font-bold text-slate-900 mt-0.5">৳ {{ parseFloat(profile ? profile.otp_rate : 0.40).toFixed(2) }}</h4>
                      </div>
                    </div>

                    <div class="bg-white p-4 md:p-5 rounded-2xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-start md:items-center gap-3 col-span-2 md:col-span-1">
                      <div class="bg-blue-50 h-10 w-10 rounded-xl flex items-center justify-center text-blue-600 shrink-0"><i class="fa-solid fa-box text-md"></i></div>
                      <div>
                        <p class="text-[10px] text-slate-400 font-bold">Today's OTPs</p>
                        <h4 class="text-sm md:text-lg font-bold text-slate-900 mt-0.5">{{ successOtps.length }} unit(s)</h4>
                      </div>
                    </div>

                  </div>
                </div>

                <div class="bg-white rounded-3xl border border-slate-200 shadow-xs overflow-hidden">
                  <div class="p-4 border-b border-slate-100 bg-slate-50/50">
                    <h4 class="font-bold text-xs text-slate-400 uppercase tracking-widest">Latest OTP Reports</h4>
                  </div>

                  <div class="block divide-y divide-slate-100">
                    <div v-if="successOtps.length === 0" class="p-8 text-center text-slate-400 font-semibold text-xs">
                      No OTP data currently available.
                    </div>
                    <div v-else v-for="log in successOtps" :key="log.created_at" class="p-4 space-y-2 text-xs">
                      <div class="flex justify-between items-center">
                        <span class="font-bold text-slate-800 text-sm">{{ log.number }}</span>
                        <span class="px-2 py-0.5 bg-[#0088CC]/10 text-[#0088CC] rounded text-[9px] font-bold uppercase">{{ log.service }}</span>
                      </div>
                      <div class="flex justify-between items-center bg-slate-50 p-2 rounded-xl">
                        <span class="text-slate-400 font-bold">OTP Code:</span>
                        <span class="font-bold text-emerald-600 text-sm">{{ log.otp_code }}</span>
                      </div>
                      <p class="text-[11px] text-slate-500 leading-relaxed font-medium"><strong class="text-slate-700">SMS Content:</strong> {{ log.message }}</p>
                    </div>
                  </div>

                </div>

              </div>

              <!-- ==================== SECTION 2: Get Number ==================== -->
              <div v-if="currentTab === 'get-number'" class="space-y-6">
                
                <div class="bg-white p-5 md:p-6 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <div class="flex items-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                    <i class="fa-solid fa-mobile-button text-[#0088CC]"></i> Target Range (e.g. 2250789XXX)
                  </div>
                  <input type="text" v-model="rid" class="w-full p-4 bg-slate-50 border border-slate-200 rounded-2xl text-lg font-black outline-none tracking-wider text-[#0088CC] focus:border-[#0088CC] text-center" />
                  
                  <div class="flex items-center gap-4 text-xs font-bold text-slate-400 py-1 justify-center">
                    <label class="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" v-model="nationalFormat" class="rounded text-[#0088CC]" /> National Format
                    </label>
                    <label class="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" v-model="removePlus" class="rounded text-[#0088CC]" /> Remove (+) Prefix
                    </label>
                  </div>

                  <button @click="handleGetNumber" :disabled="loadingNumber" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-4 rounded-2xl shadow-md transition flex items-center justify-center gap-2 disabled:bg-slate-300 active:scale-[0.98]">
                    <i v-if="loadingNumber" class="fa-solid fa-spinner animate-spin"></i>
                    <span class="tracking-widest font-black"><i class="fa-solid fa-bolt mr-1"></i> GET NUMBER</span>
                  </button>
                </div>

                <div class="space-y-4">
                  
                  <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 px-2">
                    <input type="text" v-model="searchQuery" placeholder="Search by number..." class="w-full sm:w-64 p-3 bg-white border border-slate-200 rounded-2xl text-xs font-semibold outline-none focus:border-[#0088CC]" />
                    <div class="flex gap-2 text-[10px] font-bold text-slate-400 items-center">
                      <button @click="prevPage" :disabled="currentPage === 1" class="bg-white border rounded-xl px-3 py-1.5 disabled:opacity-50 shadow-xs">Prev</button>
                      <span>Page {{ currentPage }} of {{ totalPages }}</span>
                      <button @click="nextPage" :disabled="currentPage === totalPages" class="bg-white border rounded-xl px-3 py-1.5 disabled:opacity-50 shadow-xs">Next</button>
                    </div>
                  </div>

                  <div v-if="paginatedAllocations.length === 0" class="bg-white p-12 text-center text-slate-400 border rounded-3xl font-semibold text-xs">
                    No allocated numbers found.
                  </div>

                  <!-- Segmented Numbers View (Redesigned: Fixed into exactly one single line/row with 3 dividing columns even on mobile screens) -->
                  <div v-else class="space-y-3">
                    <div v-for="alloc in paginatedAllocations" :key="alloc.createdAt" class="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-xs hover:shadow-sm hover:border-slate-300 transition">
                      
                      <!-- Row Grid layout structured explicitly into 3 columns side-by-side, divided with vertical border borders -->
                      <div class="grid grid-cols-3 divide-x divide-slate-150 items-stretch min-h-[90px]">
                        
                        <!-- COLUMN 1: COUNTRY & NUMBER -->
                        <div class="p-3 flex flex-col justify-between min-w-0">
                          <div>
                            <p class="text-[9px] md:text-[10px] text-slate-400 font-extrabold uppercase tracking-tight">COUNTRY & NUMBER</p>
                            <div @click="copyToClipboard(alloc.number)" class="flex items-center gap-1 mt-1 cursor-pointer hover:opacity-80 active:scale-95 transition">
                              <span class="font-extrabold text-slate-800 text-[11px] md:text-sm tracking-tight break-all select-all">{{ alloc.number }}</span>
                              <i class="fa-regular fa-copy text-[9px] text-[#0088CC] shrink-0"></i>
                            </div>
                          </div>
                          <div class="pt-1 leading-tight">
                            <p class="font-black text-slate-700 text-[10px] md:text-xs uppercase truncate">{{ alloc.country }}</p>
                            <p class="text-[8px] text-slate-400 font-black uppercase mt-0.5 truncate">{{ alloc.operator }}</p>
                          </div>
                        </div>

                        <!-- COLUMN 2: SMS -->
                        <div class="p-3 flex flex-col justify-center min-w-0">
                          <p class="text-[9px] md:text-[10px] text-slate-400 font-extrabold uppercase tracking-tight mb-1">SMS MESSAGE</p>
                          
                          <div v-if="alloc.status === 'active'" class="text-[10px] text-amber-600 font-black italic animate-pulse flex items-center gap-1">
                            <i class="fa-solid fa-spinner animate-spin text-[9px]"></i> Waiting...
                          </div>
                          
                          <div v-else-if="alloc.status === 'completed'" class="flex flex-col gap-1 min-w-0">
                            <div @click="copyFullSms(alloc.message)" class="bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 p-1.5 rounded-xl text-emerald-800 text-center cursor-pointer active:scale-95 transition flex items-center justify-between gap-1 group min-w-0">
                              <div class="text-left truncate">
                                <span class="text-[8px] text-emerald-600 font-bold uppercase tracking-tight block">OTP Code</span>
                                <span class="text-xs md:text-sm font-black text-emerald-800 tracking-wider block truncate">
                                  {{ alloc.otp }}
                                </span>
                              </div>
                              <i class="fa-regular fa-copy text-[9px] text-emerald-500 group-hover:text-emerald-700 shrink-0"></i>
                            </div>
                          </div>
                          
                          <div v-else class="text-[9px] text-rose-500 font-bold flex items-center gap-1">
                            <i class="fa-solid fa-circle-exclamation shrink-0"></i> Expired
                          </div>
                        </div>

                        <!-- COLUMN 3: REMAINING TIME -->
                        <div class="p-3 flex flex-col justify-between items-end">
                          <div class="text-right w-full">
                            <p class="text-[9px] md:text-[10px] text-slate-400 font-extrabold uppercase tracking-tight">REMAINING TIME</p>
                            <div class="inline-block mt-1 bg-slate-50 border border-slate-200 text-slate-700 text-[10px] md:text-xs font-black py-0.5 px-2 rounded-lg tracking-wider text-center">
                              {{ alloc.status === 'active' && alloc.timeLeft > 0 ? formatTime(alloc.timeLeft) : '--:--' }}
                            </div>
                          </div>
                          <div class="pt-1 flex justify-end w-full">
                            <span v-if="alloc.status === 'active'" class="bg-amber-50 text-amber-600 text-[8px] font-black px-1.5 py-0.5 rounded uppercase flex items-center gap-0.5 shrink-0">
                              <i class="fa-solid fa-spinner animate-spin text-[7px]"></i> PEND
                            </span>
                            <span v-else-if="alloc.status === 'completed'" class="bg-emerald-100 text-emerald-800 text-[8px] font-black px-1.5 py-0.5 rounded uppercase shrink-0">
                              SUCCESS
                            </span>
                            <span v-else class="bg-slate-100 text-slate-500 text-[8px] font-black px-1.5 py-0.5 rounded uppercase shrink-0">
                              EXPIRED
                            </span>
                          </div>
                        </div>

                      </div>
                    </div>
                  </div>

                </div>

              </div>

              <!-- ==================== SECTION 3: Radar Console ==================== -->
              <div v-if="currentTab === 'console'" class="space-y-6">
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs flex justify-between items-center">
                  <div>
                    <div class="flex items-center gap-2">
                      <i class="fa-solid fa-satellite-dish text-[#0088CC] text-lg animate-pulse"></i>
                      <h2 class="text-md font-black text-slate-900">GLOBAL INTERCEPT RADAR</h2>
                    </div>
                    <p class="text-[10px] text-slate-400 font-medium mt-1">Click on any intercepted signal card to copy its range.</p>
                  </div>
                </div>

                <div class="space-y-3">
                  <div v-if="liveLogs.length === 0" class="p-12 text-slate-400 text-center font-semibold bg-white border rounded-3xl text-xs">Initializing global signal tracker...</div>
                  
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

              <!-- ==================== SECTION 4: Payment & Withdraw ==================== -->
              <div v-if="currentTab === 'payment'" class="space-y-6">
                
                <div class="bg-white p-5 rounded-3xl border border-[#0088CC]/20 shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-800 flex items-center gap-2"><i class="fa-solid fa-wallet text-[#0088CC]"></i> Configure Wallet Address (Binance / TRC20)</h3>
                  
                  <div class="bg-indigo-50/50 border border-indigo-100 p-4 rounded-xl flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                    <div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase">Binance Pay ID / TRC20 Destination</p>
                      <p class="font-mono font-black text-indigo-700 mt-1 select-all break-all">{{ user?.wallet_address || 'No wallet address configured' }}</p>
                    </div>
                    <span class="bg-[#0088CC] text-white text-[10px] font-bold px-2.5 py-1 rounded-full shadow-sm"><i class="fa-brands fa-bitcoin"></i> TRC20</span>
                  </div>

                  <div class="flex flex-col sm:flex-row gap-2 pt-2">
                    <input type="text" v-model="walletAddressInput" placeholder="Enter Binance Pay ID or TRC20 address" class="flex-1 p-3.5 bg-slate-50 border border-slate-200 rounded-2xl text-xs font-semibold outline-none focus:border-[#0088CC] transition" />
                    <button @click="handleUpdateWallet" :disabled="walletLoading" class="bg-[#0088CC] hover:bg-[#0077B5] text-white font-black px-5 py-3.5 rounded-2xl text-xs tracking-wider transition active:scale-95 disabled:bg-slate-300 shrink-0">
                      {{ walletLoading ? 'Saving...' : 'Save Wallet' }}
                    </button>
                  </div>
                </div>

                <!-- Withdrawal Request Form -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-800 flex items-center gap-2">
                    <i class="fa-solid fa-hand-holding-dollar text-emerald-600"></i> Withdraw Request
                  </h3>
                  <p class="text-[11px] text-slate-400 leading-relaxed font-semibold">Request a withdrawal of your earnings to your saved wallet address.</p>
                  
                  <div class="grid sm:grid-cols-2 gap-3 text-xs font-bold">
                    <div>
                      <label class="text-slate-400">Withdraw Amount (৳)</label>
                      <input type="number" step="1" v-model="withdrawAmount" placeholder="e.g., 50" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl" />
                    </div>
                    <div>
                      <label class="text-slate-400">Payment Method</label>
                      <select v-model="withdrawMethod" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl">
                        <option value="TRC20">USDT (TRC20)</option>
                        <option value="Binance Pay">Binance Pay ID</option>
                      </select>
                    </div>
                  </div>

                  <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 border-t pt-3">
                    <div class="text-[11px] font-bold text-slate-500">
                      Destination Address: <span class="text-[#0088CC] font-mono select-all">{{ user?.wallet_address || 'Please set a wallet address first.' }}</span>
                    </div>
                    <button @click="submitWithdrawal" :disabled="!user?.wallet_address || withdrawAmount <= 0" class="bg-emerald-600 hover:bg-emerald-700 text-white font-black px-6 py-3 rounded-xl text-xs transition flex items-center gap-1.5 disabled:bg-slate-200 shadow-sm active:scale-95">
                      <i class="fa-solid fa-paper-plane"></i> Submit Request
                    </button>
                  </div>
                </div>

                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs flex justify-between items-center">
                  <div>
                    <p class="text-[10px] font-bold text-slate-400 uppercase">Total Accumulated Earnings</p>
                    <h2 class="text-xl font-black text-[#0088CC] mt-0.5">৳ {{ parseFloat(profile ? profile.balance : 0).toFixed(2) }}</h2>
                  </div>
                  <div class="bg-[#0088CC]/10 h-10 w-10 rounded-full flex items-center justify-center text-[#0088CC] text-md font-bold">৳</div>
                </div>
              </div>

              <!-- ==================== SECTION 5: Profile Details ==================== -->
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
                  <h3 class="font-bold text-slate-800 border-b border-slate-100 pb-2">Profile Information</h3>
                  <div class="space-y-4 font-semibold">
                    <p class="text-slate-500">User ID Code: <span class="text-slate-800 font-bold ml-1">{{ profile ? profile.uid : 'N/A' }}</span></p>
                    
                    <div class="space-y-2">
                      <p class="text-slate-500">API Access Key:</p>
                      
                      <div v-if="profile && profile.api_key" class="flex flex-col gap-2">
                        <span class="text-slate-800 font-mono text-[10px] bg-slate-50 px-3 py-2 rounded border break-all select-all">
                          {{ profile.api_key }}
                        </span>
                        <div class="flex gap-2">
                          <button @click="copyToClipboard(profile.api_key)" class="bg-[#0088CC]/10 text-[#0088CC] font-bold px-3 py-1.5 rounded-xl text-[10px] hover:bg-[#0088CC]/20 transition flex items-center gap-1">
                            Copy API Key <i class="fa-solid fa-copy"></i>
                          </button>
                        </div>
                      </div>
                      
                      <div v-else class="space-y-2">
                        <p class="text-amber-600 text-[10px] font-bold"><i class="fa-solid fa-triangle-exclamation"></i> No active API key found. Generate your API key below.</p>
                        <button @click="handleGenerateApiKey" :disabled="apiGenLoading" class="bg-emerald-600 hover:bg-emerald-700 text-white font-black px-4 py-2.5 rounded-2xl text-[11px] tracking-wider transition active:scale-95 disabled:bg-slate-300">
                          {{ apiGenLoading ? 'Generating...' : 'GENERATE API KEY' }}
                        </button>
                      </div>
                    </div>

                    <div class="mt-4 border-t pt-3 flex items-center justify-between">
                      <span class="text-slate-500 font-bold">API Documentation & Test Lab:</span>
                      <button @click="currentTab = 'api-docs'" class="bg-[#0088CC]/10 hover:bg-[#0088CC]/20 text-[#0088CC] font-black px-3.5 py-2 rounded-xl text-[10px] flex items-center gap-1.5 transition">
                        <i class="fa-solid fa-code"></i> API Docs & Test Lab
                      </button>
                    </div>

                  </div>
                </div>
              </div>

              <!-- ==================== SECTION 6: API Docs & Test Lab ==================== -->
              <div v-if="currentTab === 'api-docs'" class="space-y-6">
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <div class="flex items-center gap-2">
                    <i class="fa-solid fa-terminal text-[#0088CC] text-lg"></i>
                    <h2 class="text-md font-black text-slate-900">Mino API Documentation & Test Lab</h2>
                  </div>
                  <p class="text-xs text-slate-500 leading-relaxed font-semibold">
                    Integrate the Mino SMS service into your custom scripts, bots, or backend using your unique API Key. Below is the API request schema and live tester.
                  </p>
                </div>

                <!-- API Routes Documentation -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-5">
                  <h3 class="font-extrabold text-xs text-slate-400 uppercase tracking-widest border-b pb-2">API Documentation Schemas</h3>
                  
                  <div class="space-y-4">
                    <!-- Route 1 -->
                    <div>
                      <span class="bg-[#0088CC] text-white text-[9px] font-black px-2.5 py-1 rounded uppercase tracking-wider">GET or POST /@public/api/getnum</span>
                      <h4 class="text-xs font-black text-slate-800 mt-2">1. Number Booking Endpoint</h4>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border mt-1.5">
                        {{ apiBaseUrl }}/@public/api/getnum?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}&rid=2250789XXX&national=1&remove_plus=1
                      </div>
                    </div>

                    <!-- Route 2 -->
                    <div>
                      <span class="bg-[#0088CC] text-white text-[9px] font-black px-2.5 py-1 rounded uppercase tracking-wider">GET or POST /@public/api/liveaccess</span>
                      <h4 class="text-xs font-black text-slate-800 mt-2">2. Client Access Status</h4>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border mt-1.5">
                        {{ apiBaseUrl }}/@public/api/liveaccess?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}
                      </div>
                    </div>

                    <!-- Route 3 -->
                    <div>
                      <span class="bg-[#0088CC] text-white text-[9px] font-black px-2.5 py-1 rounded uppercase tracking-wider">GET or POST /@public/api/success-otp</span>
                      <h4 class="text-xs font-black text-slate-800 mt-2">3. Success OTP logs</h4>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border mt-1.5">
                        {{ apiBaseUrl }}/@public/api/success-otp?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}
                      </div>
                    </div>

                    <!-- Route 4 -->
                    <div>
                      <span class="bg-[#0088CC] text-white text-[9px] font-black px-2.5 py-1 rounded uppercase tracking-wider">GET or POST /@public/api/console</span>
                      <h4 class="text-xs font-black text-slate-800 mt-2">4. Console Tracker signal stream</h4>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border mt-1.5">
                        {{ apiBaseUrl }}/@public/api/console?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Live API Tester (Dynamic test engine for all 4 APIs) -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <h3 class="text-xs font-black text-slate-800 flex items-center gap-2">
                    <i class="fa-solid fa-flask text-emerald-600"></i> Live API Tester
                  </h3>
                  
                  <div class="grid sm:grid-cols-3 gap-3 text-xs font-bold">
                    
                    <!-- Dropdown api selector -->
                    <div>
                      <label class="text-slate-400">Select Target Endpoint</label>
                      <select v-model="selectedTestApi" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl font-semibold outline-none focus:border-[#0088CC]">
                        <option value="getnum">getnum (Allocate Number)</option>
                        <option value="liveaccess">liveaccess (Check Access Status)</option>
                        <option value="success-otp">success-otp (Success logs)</option>
                        <option value="console">console (Live Stream Logs)</option>
                      </select>
                    </div>

                    <!-- Input range (conditional display) -->
                    <div v-if="selectedTestApi === 'getnum'">
                      <label class="text-slate-400">Target Range ID</label>
                      <input type="text" v-model="testRange" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl" />
                    </div>

                    <!-- Exec button -->
                    <div class="flex items-end" :class="selectedTestApi !== 'getnum' ? 'col-span-2' : ''">
                      <button @click="runLiveApiTest" :disabled="testApiLoading" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-3 rounded-xl transition flex items-center justify-center gap-1.5 disabled:bg-slate-200">
                        <i v-if="testApiLoading" class="fa-solid fa-spinner animate-spin"></i>
                        <span>Execute API Test</span>
                      </button>
                    </div>

                  </div>

                  <!-- Test Response -->
                  <div v-if="testApiResponse" class="mt-3">
                    <span class="text-[9px] text-slate-400 font-bold uppercase block mb-1">API Response Payload (402 returned on auth failure):</span>
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
            const mobileMenuOpen = ref(false);

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

            // Live Test Lab Variables (Added interactive dropdown mapping logic)
            const selectedTestApi = ref('getnum');
            const testRange = ref('2250789XXX');
            const testApiLoading = ref(false);
            const testApiResponse = ref(null);
            const apiBaseUrl = ref(window.location.origin);

            // Withdrawal Variables 
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
              triggerToast("Copied: " + text);
            };

            const copyFullSms = (messageText) => {
              if (!messageText) return;
              navigator.clipboard.writeText(messageText);
              triggerToast("Full OTP SMS message copied! ✅");
            };

            const navigateMobile = (tabName) => {
              currentTab.value = tabName;
              mobileMenuOpen.value = false;
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

              // 1. Fetch User Profile Details
              try {
                const profileRes = await fetch('/api/v1/auth/me', {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                
                if (profileRes.status === 401 || profileRes.status === 402) {
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

              // 2. Poll active number allocations
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
                      triggerToast("New OTP message received! 🔔");
                    }
                  }
                } catch (e) {}
              }

              // 3. Fetch Signal Radar Logs
              try {
                const consoleRes = await fetch('/api/v1/live-console');
                const consoleData = await consoleRes.json();
                if (consoleData.status === 'success') {
                  liveLogs.value = consoleData.data;
                }
              } catch (e) {}

              // 4. Fetch Dashboard OTP Report data
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
                  triggerToast("Wallet address successfully configured! ✅");
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("Failed to update wallet address.");
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
                  triggerToast("API Access Key generated! ✅");
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("Could not generate API Access Key.");
              }
              apiGenLoading.value = false;
            };

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
                  alert("Your withdrawal request has been submitted.");
                  withdrawAmount.value = '';
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("An error occurred while submitting withdrawal request.");
              }
            };

            // Dynamic test script targeting selected APIs dynamically
            const runLiveApiTest = async () => {
              if (!profile.value?.api_key) {
                alert("Please generate an API Key first.");
                return;
              }
              testApiLoading.value = true;
              testApiResponse.value = null;
              try {
                let url = '';
                if (selectedTestApi.value === 'getnum') {
                  url = `/@public/api/getnum?api_key=${profile.value.api_key}&rid=${testRange.value}`;
                } else if (selectedTestApi.value === 'liveaccess') {
                  url = `/@public/api/liveaccess?api_key=${profile.value.api_key}`;
                } else if (selectedTestApi.value === 'success-otp') {
                  url = `/@public/api/success-otp?api_key=${profile.value.api_key}`;
                } else if (selectedTestApi.value === 'console') {
                  url = `/@public/api/console?api_key=${profile.value.api_key}`;
                }
                const res = await fetch(url);
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
                     alert("Your account has been registered successfully. Please wait for admin approval.");
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
                alert(err.message || 'Authentication process failed.');
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
                  triggerToast("Number successfully allocated!");
                  fetchData(); 
                } else {
                  alert(data.message);
                }
              } catch (err) {
                alert('Failed to allocate number');
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

            return {
              userLoaded, user, profile, authName, authEmail, authPassword, isRegistering, authLoading,
              currentTab, announcement, mobileMenuOpen, navigateMobile, rid, nationalFormat, removePlus, activeNumber, activeCountry, activeOperator, otpResult, loadingNumber, liveLogs, successOtps,
              allocations, currentPage, itemsPerPage, paginatedAllocations, totalPages, prevPage, nextPage, searchQuery,
              showToast, toastMessage, copyToClipboard, copyFullSms, walletAddressInput, walletLoading, handleUpdateWallet,
              handleAuth, signOut, handleGetNumber, formatTime, formatTimestamp,
              apiGenLoading, handleGenerateApiKey, selectedTestApi, runLiveApiTest, testRange, testApiLoading, testApiResponse, apiBaseUrl,
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
# Master Admin Panel UI (Unchanged)
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

        <!-- Loading Screen Overlay -->
        <div v-if="loading" class="fixed inset-0 bg-slate-50 flex flex-col items-center justify-center space-y-4 z-50">
          <div class="h-12 w-12 border-4 border-rose-600 border-t-transparent rounded-full animate-spin"></div>
          <p class="text-xs font-black text-rose-600 uppercase tracking-widest animate-pulse">MINO MASTER ADMIN LOADING...</p>
        </div>

        <div v-cloak v-else>

          <!-- Toast Notifications -->
          <div v-if="toast" class="fixed top-5 left-1/2 -translate-x-1/2 bg-slate-900 text-white font-black text-xs px-5 py-3 rounded-2xl shadow-xl z-[9999] transition animate-bounce">
            {{ toastMessage }}
          </div>

          <!-- Admin Login Form -->
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

          <!-- Master Admin Dashboard Area -->
          <div v-else class="min-h-screen flex flex-col md:flex-row">
            
            <!-- Sidebar -->
            <aside class="w-full md:w-64 bg-slate-900 text-slate-300 flex flex-col shrink-0">
              <div class="p-6 border-b border-slate-800 flex items-center gap-3 bg-slate-950">
                <span class="px-2 py-0.5 bg-rose-600 rounded text-white font-black text-xs">ADMIN</span>
                <span class="text-md font-black text-white">MINO SMS</span>
              </div>

              <nav class="flex-1 p-4 space-y-1">
                <button @click="currentTab = 'dashboard'" :class="currentTab === 'dashboard' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-chart-line"></i> Dashboard Overview
                </button>
                <button @click="currentTab = 'users'" :class="currentTab === 'users' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-users"></i> User Administration
                </button>
                <button @click="currentTab = 'withdrawals'" :class="currentTab === 'withdrawals' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-money-bill-transfer"></i> Withdrawal Requests
                </button>
                <button @click="currentTab = 'allocations'" :class="currentTab === 'allocations' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-mobile-screen"></i> Number Tracking Logs
                </button>
                <button @click="currentTab = 'otp-logs'" :class="currentTab === 'otp-logs' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-envelope-open-text"></i> Global OTP logs
                </button>
                <button @click="currentTab = 'settings'" :class="currentTab === 'settings' ? 'bg-rose-600 text-white' : 'hover:bg-slate-800 text-slate-400'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-xs font-bold transition text-left">
                  <i class="fa-solid fa-gears"></i> System Settings & Controls
                </button>
              </nav>

              <div class="p-4 border-t border-slate-800 flex items-center justify-between bg-slate-950 text-xs font-bold">
                <span>ADMIN PORTAL</span>
                <button @click="logOut" class="text-rose-400 hover:text-rose-600 font-black"><i class="fa-solid fa-right-from-bracket"></i> LOGOUT</button>
              </div>
            </aside>

            <!-- Main Content Area -->
            <main class="flex-1 p-4 md:p-8 space-y-6 overflow-y-auto">
              
              <header class="flex justify-between items-center border-b border-slate-200 pb-4">
                <h2 class="text-md md:text-lg font-black text-slate-900 capitalize">{{ currentTab }} Management</h2>
                <div class="text-xs font-black bg-rose-100 text-rose-600 px-3 py-1.5 rounded-full shadow-sm uppercase tracking-wider">
                  Live Master Admin
                </div>
              </header>

              <!-- ==================== Tab 1: Dashboard Overview ==================== -->
              <div v-if="currentTab === 'dashboard'" class="space-y-6">
                <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wide">Total Users</p>
                    <h3 class="text-2xl font-black text-slate-900 mt-2">{{ stats.total_users }}</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between border-amber-200 bg-amber-50/20 animate-pulse">
                    <p class="text-[10px] text-amber-600 font-bold uppercase tracking-wide">Pending Registrations</p>
                    <h3 class="text-2xl font-black text-amber-600 mt-2">{{ stats.pending_users }}</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wide">Total Allocations</p>
                    <h3 class="text-2xl font-black text-slate-900 mt-2">{{ stats.total_allocations }}</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wide">Successful OTPs</p>
                    <h3 class="text-2xl font-black text-emerald-600 mt-2">{{ stats.total_otps }}</h3>
                  </div>
                  <div class="bg-white p-5 rounded-2xl border border-indigo-200 bg-indigo-50/10 shadow-xs flex flex-col justify-between">
                    <p class="text-[10px] text-indigo-600 font-bold uppercase tracking-wide">Withdrawal Requests</p>
                    <h3 class="text-2xl font-black text-indigo-600 mt-2">{{ stats.total_withdrawals }}</h3>
                  </div>
                </div>

                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-3">
                  <h4 class="font-bold text-xs text-slate-400 uppercase tracking-widest">System Quick Controls</h4>
                  <div class="grid md:grid-cols-2 gap-4">
                    <div class="bg-slate-50 p-4 rounded-2xl border flex items-center justify-between">
                      <div>
                        <p class="text-xs font-black text-slate-700">Maintenance Mode</p>
                        <p class="text-[10px] text-slate-400 mt-0.5">Enabling this option suspends access to the general user panel.</p>
                      </div>
                      <button @click="toggleMaintenanceMode" :class="stats.maintenance_mode ? 'bg-amber-600 text-white' : 'bg-slate-200 text-slate-600'" class="px-4 py-2 rounded-xl text-xs font-black transition">
                        {{ stats.maintenance_mode ? 'ACTIVE' : 'INACTIVE' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ==================== Tab 2: User Administration ==================== -->
              <div v-if="currentTab === 'users'" class="space-y-4">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                  <input type="text" v-model="searchQuery" placeholder="Search users by name, email, or ID code..." class="w-full sm:w-80 p-3 bg-white border rounded-2xl text-xs font-semibold outline-none focus:border-rose-600" />
                  
                  <button @click="exportUsersToCSV" class="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold px-4 py-2 rounded-xl transition flex items-center gap-1">
                    <i class="fa-solid fa-file-csv"></i> Export Users CSV
                  </button>
                </div>

                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">User & ID Code</th>
                          <th class="p-4">Email & Credentials</th>
                          <th class="p-4">Balance</th>
                          <th class="p-4">OTP Rate (৳)</th>
                          <th class="p-4">Status</th>
                          <th class="p-4 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="filteredUsers.length === 0">
                          <td colspan="6" class="p-8 text-center text-slate-400 font-bold">No users match your criteria.</td>
                        </tr>
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
                            <span v-if="u.status === 'approved'" class="bg-emerald-100 text-emerald-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Approved</span>
                            <span v-else-if="u.status === 'pending'" class="bg-amber-100 text-amber-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Pending</span>
                            <span v-else class="bg-rose-100 text-rose-800 text-[10px] font-black px-2.5 py-1 rounded-full uppercase">Banned</span>
                          </td>
                          <td class="p-4 text-right space-x-1 whitespace-nowrap">
                            <button @click="openEditModal(u)" class="bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[11px] font-bold px-3 py-1.5 rounded-xl transition">Edit</button>
                            <button @click="deleteUser(u.uid)" class="bg-rose-50 hover:bg-rose-100 text-rose-700 text-[11px] font-bold px-3 py-1.5 rounded-xl transition">Delete</button>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                <!-- User Modal Edit Details -->
                <div v-if="editUser" class="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                  <div class="bg-white p-6 rounded-3xl border shadow-xl max-w-md w-full space-y-4">
                    <div class="flex justify-between items-center border-b pb-2">
                      <h3 class="font-black text-slate-900 text-sm">Edit Account: {{ editUser.name }}</h3>
                      <button @click="editUser = null" class="text-slate-400 hover:text-rose-600"><i class="fa-solid fa-xmark text-lg"></i></button>
                    </div>

                    <div class="space-y-3 text-xs font-bold">
                      <div>
                        <label class="text-slate-400">Manual Balance Edit (৳)</label>
                        <input type="number" step="0.01" v-model="editUser.balance" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm font-black outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">Custom OTP Rate (৳)</label>
                        <input type="number" step="0.01" v-model="editUser.otp_rate" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm font-black outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">Reset User Password</label>
                        <input type="text" v-model="editUser.password" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">Saved Wallet Address</label>
                        <input type="text" v-model="editUser.wallet_address" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">API Key Override</label>
                        <input type="text" v-model="editUser.api_key" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none font-mono focus:border-rose-600" />
                      </div>
                      <div>
                        <label class="text-slate-400">Account Authorization Status</label>
                        <select v-model="editUser.status" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none focus:border-rose-600">
                          <option value="approved">Approved (Active)</option>
                          <option value="pending">Pending (Awaiting Approval)</option>
                          <option value="banned">Banned (Disabled)</option>
                        </select>
                      </div>
                    </div>

                    <div class="flex gap-2 pt-2">
                      <button @click="editUser = null" class="flex-1 bg-slate-100 hover:bg-slate-200 text-slate-600 font-bold py-3 rounded-xl text-xs transition">Cancel</button>
                      <button @click="saveUserChanges" class="flex-1 bg-rose-600 hover:bg-rose-700 text-white font-bold py-3 rounded-xl text-xs transition">Save Changes</button>
                    </div>
                  </div>
                </div>

              </div>

              <!-- ==================== Tab 3: Withdrawal Requests ==================== -->
              <div v-if="currentTab === 'withdrawals'" class="space-y-4">
                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">User & Account Details</th>
                          <th class="p-4">Amount Requested</th>
                          <th class="p-4">Method</th>
                          <th class="p-4">Destination Wallet Address</th>
                          <th class="p-4">Status</th>
                          <th class="p-4">Requested At</th>
                          <th class="p-4 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="withdrawals.length === 0">
                          <td colspan="7" class="p-8 text-center text-slate-400 font-bold">No withdrawal requests found.</td>
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
                            <span v-else class="text-slate-400 italic">Completed</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <!-- ==================== Tab 4: Number Tracking Logs ==================== -->
              <div v-if="currentTab === 'allocations'" class="space-y-4">
                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">User Key</th>
                          <th class="p-4">Allocated Number</th>
                          <th class="p-4">Range ID</th>
                          <th class="p-4">Country & Provider</th>
                          <th class="p-4">Status</th>
                          <th class="p-4">Created At</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="allocations.length === 0">
                          <td colspan="6" class="p-8 text-center text-slate-400 font-bold">No active or historic allocations found.</td>
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

              <!-- ==================== Tab 5: Global OTP logs ==================== -->
              <div v-if="currentTab === 'otp-logs'" class="space-y-4">
                <div class="bg-white rounded-3xl border shadow-xs overflow-hidden">
                  <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr class="bg-slate-50 border-b border-slate-100 text-slate-400 uppercase tracking-wider font-bold">
                          <th class="p-4">User Key</th>
                          <th class="p-4">Number</th>
                          <th class="p-4">Service</th>
                          <th class="p-4">OTP Code</th>
                          <th class="p-4">SMS Content</th>
                          <th class="p-4">Revenue</th>
                          <th class="p-4">Logged At</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="otpLogs.length === 0">
                          <td colspan="7" class="p-8 text-center text-slate-400 font-bold">No global OTP logs recorded.</td>
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

              <!-- ==================== Tab 6: System Settings & Controls ==================== -->
              <div v-if="currentTab === 'settings'" class="space-y-6">
                
                <!-- Announcement Banner Controls -->
                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-400 uppercase tracking-widest flex items-center gap-2">
                    <i class="fa-solid fa-bullhorn text-rose-600"></i> Global Announcement Control Banner
                  </h3>
                  <textarea v-model="announcementInput" rows="2" placeholder="Enter notice updates or special offers..." class="w-full p-3 bg-slate-50 border rounded-xl text-xs outline-none focus:border-rose-600 font-semibold"></textarea>
                  <button @click="updateAnnouncement" class="bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold px-4 py-2.5 rounded-xl transition">
                    Publish Banner Update
                  </button>
                </div>

                <!-- Database Backup and Monitoring Configurations -->
                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-400 uppercase tracking-widest flex items-center gap-2">
                    <i class="fa-solid fa-database text-rose-600"></i> Database Backup & Security Monitoring
                  </h3>
                  
                  <div class="grid md:grid-cols-2 gap-4 text-xs font-semibold">
                    <div class="bg-slate-50 p-4 rounded-xl border flex flex-col justify-between">
                      <div>
                        <p class="font-black text-slate-800">One-Click Database Export (JSON)</p>
                        <p class="text-[10px] text-slate-400 mt-1">Safely back up the entire Firebase DB structural tree instantly.</p>
                      </div>
                      <button @click="downloadBackup" class="w-max mt-3 bg-rose-600 hover:bg-rose-700 text-white font-bold px-4 py-2 rounded-xl transition">
                        Download JSON Backup
                      </button>
                    </div>

                    <div class="bg-slate-50 p-4 rounded-xl border">
                      <p class="font-black text-slate-800">Operational Configurations Active</p>
                      <ul class="text-[10px] text-slate-500 mt-2 list-disc list-inside space-y-1">
                        <li><strong>Rule 11:</strong> Verification check active on Firebase database operations.</li>
                        <li><strong>Rule 12:</strong> Default signup state holds as Pending for admin validation.</li>
                        <li><strong>Rule 13:</strong> Realtime fallback routing config dynamically mapped to secondary gateways.</li>
                        <li><strong>Rule 14:</strong> Custom OTP custom rates configurable per unique User ID.</li>
                        <li><strong>Rule 15:</strong> Password override structures active on backend user structures.</li>
                        <li><strong>Rule 16:</strong> Automatic database backup generators and sync loops.</li>
                        <li><strong>Rule 17:</strong> Global maintenance status checks enabled on before_request scopes.</li>
                        <li><strong>Rule 18:</strong> Signal Intercept radars mapped to STEX streams.</li>
                        <li><strong>Rule 19:</strong> Safe environment private credentials decoded during start cycles.</li>
                        <li><strong>Rule 20:</strong> Dynamic 18-minute allocation countdown timer actively enforced.</li>
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
            const mobileMenuOpen = ref(false);

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

            // Live Test Lab Variables (Interactive dropdown mapping added for testing all 4 APIs)
            const selectedTestApi = ref('getnum');
            const testRange = ref('2250789XXX');
            const testApiLoading = ref(false);
            const testApiResponse = ref(null);
            const apiBaseUrl = ref(window.location.origin);

            // Withdrawal Variables 
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
              triggerToast("Copied: " + text);
            };

            const copyFullSms = (messageText) => {
              if (!messageText) return;
              navigator.clipboard.writeText(messageText);
              triggerToast("Full OTP SMS message copied! ✅");
            };

            const navigateMobile = (tabName) => {
              currentTab.value = tabName;
              mobileMenuOpen.value = false;
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

              // 1. Fetch User Profile Details
              try {
                const profileRes = await fetch('/api/v1/auth/me', {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                
                if (profileRes.status === 401 || profileRes.status === 402) {
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

              // 2. Poll active number allocations
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
                      triggerToast("New OTP message received! 🔔");
                    }
                  }
                } catch (e) {}
              }

              // 3. Fetch Signal Radar Logs
              try {
                const consoleRes = await fetch('/api/v1/live-console');
                const consoleData = await consoleRes.json();
                if (consoleData.status === 'success') {
                  liveLogs.value = consoleData.data;
                }
              } catch (e) {}

              // 4. Fetch Dashboard OTP Report data
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
                  triggerToast("Wallet address successfully configured! ✅");
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("Failed to update wallet address.");
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
                  triggerToast("API Access Key generated! ✅");
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("Could not generate API Access Key.");
              }
              apiGenLoading.value = false;
            };

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
                  alert("Your withdrawal request has been submitted.");
                  withdrawAmount.value = '';
                  fetchData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("An error occurred while submitting withdrawal request.");
              }
            };

            // Dynamic test script targeting selected APIs dynamically
            const runLiveApiTest = async () => {
              if (!profile.value?.api_key) {
                alert("Please generate an API Key first.");
                return;
              }
              testApiLoading.value = true;
              testApiResponse.value = null;
              try {
                let url = '';
                if (selectedTestApi.value === 'getnum') {
                  url = `/@public/api/getnum?api_key=${profile.value.api_key}&rid=${testRange.value}`;
                } else if (selectedTestApi.value === 'liveaccess') {
                  url = `/@public/api/liveaccess?api_key=${profile.value.api_key}`;
                } else if (selectedTestApi.value === 'success-otp') {
                  url = `/@public/api/success-otp?api_key=${profile.value.api_key}`;
                } else if (selectedTestApi.value === 'console') {
                  url = `/@public/api/console?api_key=${profile.value.api_key}`;
                }
                const res = await fetch(url);
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
                     alert("Your account has been registered successfully. Please wait for admin approval.");
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
                alert(err.message || 'Authentication process failed.');
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
                  triggerToast("Number successfully allocated!");
                  fetchData(); 
                } else {
                  alert(data.message);
                }
              } catch (err) {
                alert('Failed to allocate number');
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

            return {
              userLoaded, user, profile, authName, authEmail, authPassword, isRegistering, authLoading,
              currentTab, announcement, mobileMenuOpen, navigateMobile, rid, nationalFormat, removePlus, activeNumber, activeCountry, activeOperator, otpResult, loadingNumber, liveLogs, successOtps,
              allocations, currentPage, itemsPerPage, paginatedAllocations, totalPages, prevPage, nextPage, searchQuery,
              showToast, toastMessage, copyToClipboard, copyFullSms, walletAddressInput, walletLoading, handleUpdateWallet,
              handleAuth, signOut, handleGetNumber, formatTime, formatTimestamp,
              apiGenLoading, handleGenerateApiKey, selectedTestApi, runLiveApiTest, testRange, testApiLoading, testApiResponse, apiBaseUrl,
              withdrawAmount, withdrawMethod, submitWithdrawal
            };
          }
        }).mount('#app');
      </script>
    </body>
    </html>
    """
    return Response(admin_html, mimetype='text/html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 4000))
    app.run(host='0.0.0.0', port=port)