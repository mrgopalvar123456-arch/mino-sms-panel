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
ADMIN_USER = os.environ.get("ADMIN_USERNAME", "Mino420@")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "Mino420@admin")
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
# Database Handlers (Optimized Queries)
# =========================================================================
COUNTRY_PREFIXES = {
    # South Asia
    "880": "Bangladesh", "91": "India", "92": "Pakistan", "94": "Sri Lanka",
    "977": "Nepal", "93": "Afghanistan", "960": "Maldives", "975": "Bhutan",
    
    # Southeast Asia & East Asia
    "86": "China", "81": "Japan", "82": "South Korea", "886": "Taiwan",
    "60": "Malaysia", "65": "Singapore", "62": "Indonesia", "66": "Thailand",
    "84": "Vietnam", "63": "Philippines", "95": "Myanmar", "855": "Cambodia",
    "856": "Laos", "673": "Brunei", "670": "East Timor", "852": "Hong Kong",
    "853": "Macau", "976": "Mongolia", "850": "North Korea",
    
    # Middle East & Central Asia
    "966": "Saudi Arabia", "971": "UAE", "965": "Kuwait", "974": "Qatar",
    "968": "Oman", "973": "Bahrain", "967": "Yemen", "962": "Jordan",
    "961": "Lebanon", "963": "Syria", "964": "Iraq", "972": "Israel",
    "98": "Iran", "90": "Turkey", "7": "Russia/Kazakhstan", "992": "Tajikistan",
    "993": "Turkmenistan", "994": "Azerbaijan", "995": "Georgia", "996": "Kyrgyzstan",
    "998": "Uzbekistan", "374": "Armenia",
    
    # Europe
    "44": "United Kingdom", "49": "Germany", "33": "France", "39": "Italy",
    "34": "Spain", "31": "Netherlands", "32": "Belgium", "41": "Switzerland",
    "43": "Austria", "46": "Sweden", "47": "Norway", "45": "Denmark",
    "358": "Finland", "353": "Ireland", "351": "Portugal", "30": "Greece",
    "48": "Poland", "420": "Czech Republic", "36": "Hungary", "40": "Romania",
    "359": "Bulgaria", "380": "Ukraine", "375": "Belarus", "381": "Serbia",
    "385": "Croatia", "386": "Slovenia", "387": "Bosnia and Herzegovina",
    "389": "North Macedonia", "355": "Albania", "373": "Moldova", "370": "Lithuania",
    "371": "Latvia", "372": "Estonia", "354": "Iceland", "356": "Malta",
    "357": "Cyprus", "376": "Andorra", "377": "Monaco", "378": "San Marino",
    "379": "Vatican City", "421": "Slovakia", "423": "Liechtenstein", "382": "Montenegro",
    
    # North America & Caribbean
    "1": "USA/Canada/Caribbean", # (Includes Jamaica, Bahamas, etc. via NANP)
    "52": "Mexico", "502": "Guatemala", "503": "El Salvador", "504": "Honduras",
    "505": "Nicaragua", "506": "Costa Rica", "507": "Panama", "53": "Cuba",
    "509": "Haiti", "501": "Belize",
    
    # South America
    "55": "Brazil", "54": "Argentina", "57": "Colombia", "58": "Venezuela",
    "51": "Peru", "56": "Chile", "593": "Ecuador", "591": "Bolivia",
    "595": "Paraguay", "598": "Uruguay", "592": "Guyana", "597": "Suriname",
    
    # Africa (Your list expanded)
    "20": "Egypt", "27": "South Africa", "234": "Nigeria", "2 Kenya": "254",
    "212": "Morocco", "213": "Algeria", "216": "Tunisia", "218": "Libya",
    "249": "Sudan", "251": "Ethiopia", "2 Somalia": "252", "2 Djibuti": "253",
    "211": "South Sudan", "221": "Senegal", "222": "Mauritania", "223": "Mali",
    "224": "Guinea", "225": "Ivory Coast", "226": "Burkina Faso", "227": "Niger",
    "228": "Togo", "229": "Benin", "230": "Mauritius", "231": "Liberia",
    "232": "Sierra Leone", "233": "Ghana", "235": "Chad", "236": "Central African Republic",
    "237": "Cameroon", "238": "Cape Verde", "239": "Sao Tome and Principe",
    "240": "Equatorial Guinea", "241": "Gabon", "242": "Congo", "243": "DR Congo",
    "244": "Angola", "245": "Guinea-Bissau", "248": "Seychelles", "250": "Rwanda",
    "254": "Kenya", "255": "Tanzania", "256": "Uganda", "257": "Burundi",
    "258": "Mozambique", "260": "Zambia", "261": "Madagascar", "262": "Reunion/Mayotte",
    "263": "Zimbabwe", "264": "Namibia", "265": "Malawi", "266": "Lesotho",
    "267": "Botswana", "268": "Eswatini", "269": "Comoros", "291": "Eritrea",
    
    # Oceania
    "61": "Australia", "64": "New Zealand", "679": "Fiji", "675": "Papua New Guinea",
    "685": "Samoa", "676": "Tonga", "677": "Solomon Islands", "678": "Vanuatu",
    "682": "Cook Islands", "687": "New Caledonia", "689": "French Polynesia"
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

# voltxsms Configuration
VOLTX_API_KEY = os.environ.get("VOLTX_API_KEY", "M9JBBKWUL33")
VOLTX_BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tnevs/@public/api"

def mask_number(number):
    if not number:
        return ''
    length = len(number)
    if length < 8:
        return number
    return f"{number[:6]}****{number[length-3:]}"

# Highly Robust Authentication Middleware supporting multiple header formats, JSON parameter inputs and forms
def get_current_user_optimized():
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        user_ref = fb_db.reference(f'/users/{token}')
        user = user_ref.get()
        if user and user.get('status', 'pending') == 'approved':
            return user

    api_key = (
        request.headers.get('X-MINO-API-KEY') or 
        request.args.get('api_key') or 
        request.form.get('api_key')
    )
    
    if not api_key and request.is_json:
        try:
            data = request.get_json(silent=True) or {}
            api_key = data.get('api_key')
        except Exception:
            pass
            
    if api_key:
        users_ref = fb_db.reference('/users')
        try:
            query = users_ref.order_by_child('api_key').equal_to(api_key).get()
            if query and isinstance(query, dict):
                for u_data in query.values():
                    if u_data.get('status', 'pending') == 'approved' and u_data.get('api_key_approved', False) is True:
                        return u_data
        except Exception:
            all_users = users_ref.get() or {}
            if isinstance(all_users, dict):
                for u_data in all_users.values():
                    if u_data.get('api_key') == api_key and u_data.get('status', 'pending') == 'approved' and u_data.get('api_key_approved', False) is True:
                        return u_data
    return None

# =========================================================================
# User Registration & Login APIs
# =========================================================================
@app.route('/api/v1/auth/register', methods=['POST'])
def register():
    try:
        data = request.get_json(silent=True) or {}
        email = data.get('email')
        password = data.get('password')
        name = data.get('name', '').strip()

        if not email or not password:
            return jsonify({'status': 'error', 'message': 'Email and password are required'}), 400

        if not name:
            name = email.split('@')[0]

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
            'api_key_approved': False,
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
        data = request.get_json(silent=True) or {}
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
        api_key_approved = user.get('api_key_approved', False)
        existing_key = user.get('api_key')
        
        if existing_key and not api_key_approved:
            return jsonify({'status': 'success', 'message': 'API Key request is pending admin approval', 'api_key': existing_key, 'api_key_approved': False})
        elif existing_key and api_key_approved:
            return jsonify({'status': 'success', 'message': 'API Key is already active and approved', 'api_key': existing_key, 'api_key_approved': True})
        
        unique_key = 'mino_live_' + secrets.token_hex(16)
        updates = {
            'api_key': unique_key,
            'api_key_approved': False
        }
        fb_db.reference(f'/users/{user_id}').update(updates)
        return jsonify({'status': 'success', 'message': 'API Key generated. Awaiting admin approval.', 'api_key': unique_key, 'api_key_approved': False})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/user/update-wallet', methods=['POST'])
def update_wallet():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402
        
        data = request.get_json(silent=True) or {}
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
        
        data = request.get_json(silent=True) or {}
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
        
        fb_db.reference(f'/users/{user_id}/balance').set(new_balance)
        
        with_id = "wd_" + secrets.token_hex(8)
        withdrawal_data = {
            'id': with_id,
            'userId': user_id,
            'userEmail': user['email'],
            'userName': user['name'],
            'amount': amount,
            'method': method,
            'address': address,
            'status': 'approved' if method == 'manual' else 'pending',
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        fb_db.reference(f'/withdrawals/{with_id}').set(withdrawal_data)
        
        return jsonify({'status': 'success', 'message': 'Withdrawal request submitted successfully.', 'new_balance': new_balance})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# Real-Time Leaderboard API (Secured - Returns 402 if Unauthorized)
# =========================================================================
@app.route('/api/v1/leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key or Unauthorized access.'}), 402

        users_dict = fb_db.reference('/users').get() or {}
        otp_logs_dict = fb_db.reference('/otp_logs').get() or {}
        
        users_list = firebase_to_list(users_dict)
        otp_logs_list = firebase_to_list(otp_logs_dict)
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        def get_hours_diff(iso_str):
            try:
                dt = parse_iso_datetime(iso_str)
                return (now - dt).total_seconds() / 3600.0
            except Exception:
                return 9999.0
        
        today_counts = {}
        weekly_counts = {}
        lifetime_counts = {}
        
        for log in otp_logs_list:
            uid = log.get('userId')
            if not uid:
                continue
            hours = get_hours_diff(log.get('createdAt'))
            
            lifetime_counts[uid] = lifetime_counts.get(uid, 0) + 1
            if hours <= 168:
                weekly_counts[uid] = weekly_counts.get(uid, 0) + 1
            if hours <= 25:
                today_counts[uid] = today_counts.get(uid, 0) + 1
                
        user_map = {u['uid']: u for u in users_list}
        
        def build_ranking(counts_map):
            ranking = []
            for uid, count in counts_map.items():
                u = user_map.get(uid)
                if u:
                    raw_name = u.get('name', 'User')
                    masked_name = raw_name[:3] + "****" if len(raw_name) > 3 else raw_name + "****"
                    ranking.append({
                        'name': masked_name,
                        'id_code': u.get('id_code', 'MINO-N/A'),
                        'count': count
                    })
            ranking.sort(key=lambda x: x['count'], reverse=True)
            return ranking[:5]
            
        t_rank = build_ranking(today_counts)
        w_rank = build_ranking(weekly_counts)
        l_rank = build_ranking(lifetime_counts)
        
        if not t_rank:
            t_rank = [
                {'name': 'Min****', 'id_code': 'MINO-8821', 'count': 14},
                {'name': 'Par****', 'id_code': 'MINO-3420', 'count': 9},
                {'name': 'Saj****', 'id_code': 'MINO-5412', 'count': 5}
            ]
        if not w_rank:
            w_rank = [
                {'name': 'Min****', 'id_code': 'MINO-8821', 'count': 82},
                {'name': 'Par****', 'id_code': 'MINO-3420', 'count': 64},
                {'name': 'Tan****', 'id_code': 'MINO-1190', 'count': 41}
            ]
        if not l_rank:
            l_rank = [
                {'name': 'Min****', 'id_code': 'MINO-8821', 'count': 430},
                {'name': 'Par****', 'id_code': 'MINO-3420', 'count': 312},
                {'name': 'Tan****', 'id_code': 'MINO-1190', 'count': 195}
            ]
            
        return jsonify({
            'status': 'success',
            'today': t_rank,
            'weekly': w_rank,
            'lifetime': l_rank
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# Public API Endpoints (GET & POST - Secured with 402 Error Code blocks)
# =========================================================================

# 1. Booking API (Supports GET and POST, robust parameter parser)
@app.route('/@public/api/getnum', methods=['POST', 'GET'])
@app.route('/api/v1/getnum', methods=['POST', 'GET'])
def getnum():
    try:
        data = {}
        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
            except Exception:
                pass
                
        form_data = request.form or {}
        args_data = request.args or {}
        
        rid = data.get('rid') or form_data.get('rid') or args_data.get('rid')
        national = data.get('national') or form_data.get('national') or args_data.get('national') or '1'
        remove_plus = data.get('remove_plus') or form_data.get('remove_plus') or args_data.get('remove_plus') or '1'

        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key or Unauthorized'}), 402

        if not rid:
            return jsonify({'status': 'error', 'message': 'Range ID missing'}), 400

        user_id = user['uid']
        
        # 12-second Rate Limit Check for users without approved API Key
        api_key_approved = user.get('api_key_approved', False)
        if not api_key_approved:
            last_booking_str = user.get('last_booking_time')
            now = datetime.datetime.now(datetime.timezone.utc)
            if last_booking_str:
                try:
                    last_booking = parse_iso_datetime(last_booking_str)
                    elapsed = (now - last_booking).total_seconds()
                    if elapsed < 12.0:
                        remaining = round(12.0 - elapsed, 1)
                        return jsonify({
                            'status': 'error', 
                            'message': f'Rate limit cooldown: Please wait {remaining} seconds before requesting a new number.'
                        }), 429
                except Exception as ex:
                    print("Cooldown parser error:", ex)
            
            fb_db.reference(f'/users/{user_id}/last_booking_time').set(now.isoformat())

        clean_rid = str(rid).upper().replace('X', '').strip()
        voltx_data = None
        last_error = "No number available on this range"

        try:
            params = {'rid': clean_rid, 'national': int(national), 'remove_plus': int(remove_plus)}
            res = requests.get(f"{VOLTX_BASE_URL}/getnum", params=params, headers={'mauthapi': VOLTX_API_KEY}, timeout=4)
            if res.status_code == 200:
                json_res = res.json()
                meta = json_res.get('meta', {})
                if meta.get('status') == 'ok' or meta.get('code') == 200:
                    voltx_data = json_res
                else:
                    last_error = json_res.get('message') or json_res.get('msg') or last_error
        except Exception as e:
            print("GET Attempt Failed:", e)

        if not voltx_data:
            try:
                payload = {'rid': clean_rid, 'national': int(national), 'remove_plus': int(remove_plus)}
                res = requests.post(f"{VOLTX_BASE_URL}/getnum", json=payload, headers={'mauthapi': VOLTX_API_KEY}, timeout=4)
                if res.status_code == 200:
                    json_res = res.json()
                    meta = json_res.get('meta', {})
                    if meta.get('status') == 'ok' or meta.get('code') == 200:
                        voltx_data = json_res
                    else:
                        last_error = json_res.get('message') or json_res.get('msg') or last_error
            except Exception as e:
                print("POST JSON Attempt Failed:", e)

        if not voltx_data:
            return jsonify({'status': 'error', 'message': last_error}), 400

        data_payload = voltx_data.get('data', {})
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

# 2. Live Access Status API (GET only - Returns EXACTLY and ONLY the real-time voltxsms raw JSON format)
@app.route('/@public/api/liveaccess', methods=['GET'])
def liveaccess():
    user = get_current_user_optimized()
    if not user:
        return jsonify({'status': 'error', 'message': 'Access Denied. Invalid or Missing API credentials.'}), 402
    
    try:
        res = requests.get(f"{VOLTX_BASE_URL}/liveaccess", headers={'mauthapi': VOLTX_API_KEY}, timeout=4)
        if res.status_code == 200:
            return Response(res.text, mimetype='application/json')
        else:
            return Response(res.text, status=res.status_code, mimetype='application/json')
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'VoltxSMS Live Access fetch failed: {str(e)}'}), 500

# 3. Successful OTP Reports API (GET only)
@app.route('/@public/api/success-otp', methods=['GET'])
@app.route('/api/v1/success-otp', methods=['GET', 'POST'])
def success_otp():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402

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

# 4. Live Console API (GET only, Array list mapping optimized)
@app.route('/@public/api/console', methods=['GET'])
@app.route('/api/v1/live-console', methods=['GET', 'POST'])
def get_live_console():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key or Unauthorized access.'}), 402

        res = requests.get(f"{VOLTX_BASE_URL}/console", headers={'mauthapi': VOLTX_API_KEY}, timeout=4)
        if res.status_code == 200:
            voltx_data = res.json()
            hits = []
            
            if isinstance(voltx_data, list):
                hits = voltx_data
            elif isinstance(voltx_data, dict):
                data_obj = voltx_data.get('data')
                if isinstance(data_obj, dict):
                    hits = data_obj.get('hits', []) or data_obj.get('ranges', [])
                elif isinstance(data_obj, list):
                    hits = data_obj
                else:
                    hits = voltx_data.get('hits', []) or voltx_data.get('ranges', [])
            
            data = []
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                
                msg = hit.get('message') or hit.get('msg')
                single_range = hit.get('range')
                sid = hit.get('sid', 'Global')
                time_val = hit.get('time') or hit.get('last_at') or 0
                
                if single_range and msg:
                    c_name = get_country_from_range(single_range)
                    data.append({
                        'range': single_range,
                        'service': sid,
                        'message': msg,
                        'time': time_val,
                        'country': c_name
                    })
                else:
                    ranges = hit.get('ranges', [])
                    if isinstance(ranges, list):
                        for r in ranges:
                            c_name = get_country_from_range(r)
                            data.append({
                                'range': r,
                                'service': sid,
                                'message': f"Signal intercepted on range {r} for {sid}",
                                'time': time_val,
                                'country': c_name
                            })
                    elif isinstance(ranges, str):
                        c_name = get_country_from_range(ranges)
                        data.append({
                            'range': ranges,
                            'service': sid,
                            'message': f"Signal intercepted on range {ranges} for {sid}",
                            'time': time_val,
                            'country': c_name
                        })
            return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        print("VoltxSMS Console API Error:", e)
    return jsonify({'status': 'success', 'data': []})

# 5. Check Single Number Status (Extremely Useful for Telegram Bots and Integrations)
@app.route('/@public/api/check', methods=['GET', 'POST'])
def check_number_status():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402

        data = {}
        if request.is_json:
            try:
                data = request.get_json(silent=True) or {}
            except Exception:
                pass
        form_data = request.form or {}
        args_data = request.args or {}
        
        target_number = data.get('number') or form_data.get('number') or args_data.get('number')
        if not target_number:
            return jsonify({'status': 'error', 'message': 'Missing number parameter'}), 400
        
        clean_target = str(target_number).replace('+', '').strip()
        
        # Search DB allocated lists
        all_allocs_dict = fb_db.reference('/allocated_numbers').get() or {}
        all_allocs_list = firebase_to_list(all_allocs_dict)
        user_id = user['uid']
        
        matched_alloc = None
        for alloc in all_allocs_list:
            if alloc.get('userId') == user_id:
                alloc_num = str(alloc.get('number', '')).replace('+', '').strip()
                if clean_target in alloc_num or alloc_num in clean_target:
                    matched_alloc = alloc
                    break
        
        if not matched_alloc:
            return jsonify({'status': 'error', 'message': 'Number allocation not found for this user'}), 404
        
        # Real-time Background sync update fallback during query
        if matched_alloc.get('status') == 'active':
            try:
                res = requests.get(f"{VOLTX_BASE_URL}/success-otp", headers={'mauthapi': VOLTX_API_KEY}, timeout=3)
                if res.status_code == 200:
                    json_data = res.json()
                    otps = json_data.get('data', {}).get('otps', [])
                    for otp_item in otps:
                        otp_num = str(otp_item.get('number', '')).replace('+', '').strip()
                        alloc_num = str(matched_alloc.get('number', '')).replace('+', '').strip()
                        if clean_target in otp_num or otp_num in clean_target:
                            message = otp_item.get('message', '')
                            
                            # Clean numeric extraction (4 to 9 digit code)
                            otp_code = ""
                            match = re.search(r'\b\d{4,9}\b', message)
                            if match:
                                otp_code = match.group(0)
                            else:
                                any_digits = re.findall(r'\d+', message)
                                otp_code = max(any_digits, key=len) if any_digits else "N/A"
                                if len(otp_code) > 9:
                                    otp_code = otp_code[:9]
                                    
                            matched_alloc['status'] = 'completed'
                            matched_alloc['otp'] = otp_code
                            matched_alloc['message'] = message
                            
                            alloc_id = matched_alloc.get('id')
                            if alloc_id:
                                fb_db.reference(f'/allocated_numbers/{alloc_id}').update({
                                    'status': 'completed',
                                    'otp': otp_code,
                                    'message': message
                                })
                                
                            service_rates = fb_db.reference('/settings/service_rates').get() or {}
                            service_rates = {k.lower(): v for k, v in service_rates.items()}
                            
                            service = 'generic'
                            msg_lower = message.lower()
                            if 'facebook' in msg_lower or 'fb' in msg_lower: service = 'facebook'
                            elif 'instagram' in msg_lower or 'ig' in msg_lower: service = 'instagram'
                            elif 'whatsapp' in msg_lower or 'wa' in msg_lower: service = 'whatsapp'
                            elif 'telegram' in msg_lower or 'tg' in msg_lower: service = 'telegram'
                            elif 'google' in msg_lower or 'g-' in msg_lower: service = 'google'
                            
                            exist_log = False
                            all_logs = fb_db.reference('/otp_logs').get() or {}
                            for item in firebase_to_list(all_logs):
                                if item.get('number') == matched_alloc['number']:
                                    exist_log = True
                                    break
                            
                            if not exist_log:
                                otp_rate = float(user.get('otp_rate', 0.40))
                                svc_config = service_rates.get(service)
                                svc_status = 'ON'
                                svc_payout_rate = otp_rate

                                if isinstance(svc_config, dict):
                                    svc_status = str(svc_config.get('status', 'ON')).upper()
                                    svc_payout_rate = float(svc_config.get('rate', otp_rate))
                                elif svc_config is not None:
                                    try:
                                        svc_payout_rate = float(svc_config)
                                    except ValueError:
                                        pass

                                earned_revenue = 0.00 if svc_status == 'OFF' else svc_payout_rate
                                new_balance = float(user.get('balance', 0.0)) + earned_revenue
                                fb_db.reference(f'/users/{user_id}/balance').set(new_balance)
                                
                                otp_id = "otp_" + secrets.token_hex(8)
                                fb_db.reference(f'/otp_logs/{otp_id}').set({
                                    'userId': user_id,
                                    'number': matched_alloc['number'],
                                    'service': service,
                                    'otpCode': otp_code,
                                    'message': message,
                                    'revenue': earned_revenue,
                                    'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
                                })
                            break
            except Exception as sync_err:
                print("Sync error during direct status check:", sync_err)
                
        return jsonify({
            'status': 'success',
            'number': matched_alloc.get('number'),
            'allocation_status': matched_alloc.get('status'),
            'otp_code': matched_alloc.get('otp', ''),
            'full_sms': matched_alloc.get('message', ''),
            'created_at': matched_alloc.get('createdAt')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# User allocations sync router - EXTREMELY OPTIMIZED
# Skip making requests to VoltxSMS if the user does not have any active allocations!
@app.route('/api/v1/user-allocations', methods=['GET'])
def get_user_allocations():
    try:
        user = get_current_user_optimized()
        if not user:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 402

        user_id = user['uid']
        otp_rate = float(user.get('otp_rate', 0.40))

        all_allocs_dict = fb_db.reference('/allocated_numbers').get() or {}
        all_allocs_list = firebase_to_list(all_allocs_dict)
        active_allocs_list = [alloc for alloc in all_allocs_list if alloc.get('userId') == user_id]

        # Only connect to VoltxSMS if the user has at least one active number allocation
        has_active_allocations = any(alloc.get('status') == 'active' for alloc in active_allocs_list)
        if has_active_allocations:
            service_rates = fb_db.reference('/settings/service_rates').get() or {}
            service_rates = {k.lower(): v for k, v in service_rates.items()}

            try:
                res = requests.get(f"{VOLTX_BASE_URL}/success-otp", headers={'mauthapi': VOLTX_API_KEY}, timeout=3)
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
                                    
                                    # Exact 4 to 9 digits clean matching system
                                    otp_code = ""
                                    match = re.search(r'\b\d{4,9}\b', message)
                                    if match:
                                        otp_code = match.group(0)
                                    else:
                                        any_digits = re.findall(r'\d+', message)
                                        if any_digits:
                                            otp_code = max(any_digits, key=len)
                                            if len(otp_code) > 9:
                                                otp_code = otp_code[:9]
                                        else:
                                            otp_code = "N/A"

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
                                        svc_config = service_rates.get(service)
                                        svc_status = 'ON'
                                        svc_payout_rate = otp_rate

                                        if isinstance(svc_config, dict):
                                            svc_status = str(svc_config.get('status', 'ON')).upper()
                                            svc_payout_rate = float(svc_config.get('rate', otp_rate))
                                        elif svc_config is not None:
                                            try:
                                                svc_payout_rate = float(svc_config)
                                            except ValueError:
                                                pass

                                        earned_revenue = 0.00 if svc_status == 'OFF' else svc_payout_rate

                                        new_balance = float(user.get('balance', 0.0)) + earned_revenue
                                        fb_db.reference(f'/users/{user_id}/balance').set(new_balance)
                                        
                                        otp_id = "otp_" + secrets.token_hex(8)
                                        fb_db.reference(f'/otp_logs/{otp_id}').set({
                                            'userId': user_id,
                                            'number': alloc['number'],
                                            'service': service,
                                            'otpCode': otp_code,
                                            'message': message,
                                            'revenue': earned_revenue,
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

        refreshed_query = fb_db.reference('/allocated_numbers').get() or {}
        refreshed_list = [a for a in firebase_to_list(refreshed_query) if a.get('userId') == user_id]
        refreshed_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)

        return jsonify({'status': 'success', 'allocations': refreshed_list})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Endpoint for Users to retrieve current service payout rates
@app.route('/api/v1/user/service-rates', methods=['GET'])
def user_get_service_rates():
    try:
        raw_rates = fb_db.reference('/settings/service_rates').get() or {}
        default_services = ['facebook', 'instagram', 'whatsapp', 'telegram', 'google', 'generic']
        rates = {}
        for svc in default_services:
            item = raw_rates.get(svc)
            if isinstance(item, dict):
                rates[svc] = {
                    'rate': float(item.get('rate', 0.40)),
                    'status': str(item.get('status', 'ON')).upper()
                }
            else:
                legacy_val = 0.40
                if item is not None:
                    try:
                        legacy_val = float(item)
                    except ValueError:
                        pass
                rates[svc] = {
                    'rate': legacy_val,
                    'status': 'ON'
                }
        return jsonify({'status': 'success', 'rates': rates})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Missing route catch handler
@app.errorhandler(404)
def resource_not_found(e):
    if request.path.startswith('/@public/api/') or request.path.startswith('/api/'):
        return jsonify({'status': 'error', 'message': 'API endpoint does not exist. Check route definition.'}), 402
    return "Page Not Found", 404

# =========================================================================
# API Routes for Admin Panel - Consolidate endpoint to fetch entire dashboard at once
# =========================================================================
@app.route('/api/v1/admin/login', methods=['POST'])
def admin_api_login():
    try:
        data = request.get_json(silent=True) or {}
        username = data.get('username')
        password = data.get('password')
        if username == ADMIN_USER and password == ADMIN_PASS:
            return jsonify({'status': 'success', 'token': ADMIN_STATIC_TOKEN})
        return jsonify({'status': 'error', 'message': 'Invalid Admin Credentials'}), 401
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# High-Performance Consolidated Admin Endpoint
@app.route('/api/v1/admin/dashboard-all', methods=['GET'])
def admin_api_dashboard_all():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        # Fetch the entire database layout once to minimize roundtrips
        db_data = fb_db.reference('/').get() or {}
        
        users_dict = db_data.get('users', {})
        users_list = firebase_to_list(users_dict)
        users_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        
        allocs_dict = db_data.get('allocated_numbers', {})
        allocs_list = firebase_to_list(allocs_dict)
        allocs_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        
        otp_logs_dict = db_data.get('otp_logs', {})
        otp_logs_list = firebase_to_list(otp_logs_dict)
        otp_logs_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        
        withdrawals_dict = db_data.get('withdrawals', {})
        withdrawals_list = firebase_to_list(withdrawals_dict)
        withdrawals_list.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        
        settings = db_data.get('settings', {})
        m_mode = settings.get('maintenance_mode', False)
        announcement = settings.get('announcement', '')
        raw_rates = settings.get('service_rates', {})
        
        default_services = ['facebook', 'instagram', 'whatsapp', 'telegram', 'google', 'generic']
        rates = {}
        for svc in default_services:
            item = raw_rates.get(svc)
            if isinstance(item, dict):
                rates[svc] = {
                    'rate': float(item.get('rate', 0.40)),
                    'status': str(item.get('status', 'ON')).upper()
                }
            else:
                legacy_val = 0.40
                if item is not None:
                    try:
                        legacy_val = float(item)
                    except ValueError:
                        pass
                default_status = 'OFF' if svc in ['whatsapp', 'telegram'] else 'ON'
                rates[svc] = {
                    'rate': legacy_val,
                    'status': default_status
                }

        pending_users = sum(1 for u in users_list if u.get('status') == 'pending')
        
        return jsonify({
            'status': 'success',
            'stats': {
                'total_users': len(users_list),
                'pending_users': pending_users,
                'total_allocations': len(allocs_list),
                'total_otps': len(otp_logs_list),
                'total_withdrawals': len(withdrawals_list),
                'maintenance_mode': bool(m_mode),
                'announcement': announcement
            },
            'users': users_list,
            'allocations': allocs_list,
            'otp_logs': otp_logs_list,
            'withdrawals': withdrawals_list,
            'rates': rates
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/users/update', methods=['POST'])
def admin_api_user_update():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
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
        if 'api_key_approved' in data:
            updates['api_key_approved'] = bool(data['api_key_approved'])
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
        data = request.get_json(silent=True) or {}
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
        data = request.get_json(silent=True) or {}
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
        data = request.get_json(silent=True) or {}
        msg = data.get('announcement', '').strip()
        fb_db.reference('/settings/announcement').set(msg)
        return jsonify({'status': 'success', 'message': 'Announcement updated'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/settings/service-rates', methods=['POST'])
def admin_set_service_rates():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        rates = data.get('rates', {})
        sanitized_rates = {}
        for k, v in rates.items():
            svc_name = str(k).strip().lower()
            if isinstance(v, dict):
                sanitized_rates[svc_name] = {
                    'rate': float(v.get('rate', 0.40)),
                    'status': str(v.get('status', 'ON')).upper()
                }
            else:
                sanitized_rates[svc_name] = {
                    'rate': float(v),
                    'status': 'ON'
                }
        fb_db.reference('/settings/service_rates').set(sanitized_rates)
        return jsonify({'status': 'success', 'message': 'Service payout rates successfully updated', 'rates': sanitized_rates})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/admin/withdrawals/action', methods=['POST'])
def admin_withdrawal_action():
    if not verify_admin():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
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

# =========================================================================
# Client-side UI Rendering (Dynamic digit boxes, and copy capabilities)
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
      <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
      <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
      <script src="https://cdn.tailwindcss.com"></script>
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
                <span class="text-lg font-black text-slate-955">MINO SMS</span>
              </div>

              <nav class="flex-1 p-4 space-y-1">
                <button @click="currentTab = 'dashboard'" :class="currentTab === 'dashboard' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-house"></i> Dashboard
                </button>
                <button @click="currentTab = 'get-number'" :class="currentTab === 'get-number' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-mobile-screen"></i> Get Number
                </button>
                <button @click="currentTab = 'console'" :class="currentTab === 'console' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-terminal"></i> Console
                </button>
                <button @click="currentTab = 'leaderboard'" :class="currentTab === 'leaderboard' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-trophy"></i> Leaderboard
                </button>
                <button @click="currentTab = 'payment'" :class="currentTab === 'payment' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-wallet"></i> Payment & Withdraw
                </button>
                <button @click="currentTab = 'profile'" :class="currentTab === 'profile' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                  <i class="fa-solid fa-user"></i> Profile Details
                </button>
              </nav>

              <!-- Support Telegram Help Desk button -->
              <div class="p-4 border-t border-slate-100 bg-slate-50/50 space-y-3">
                <a href="https://t.me/MinoXSupport0" target="_blank" class="flex items-center gap-2 text-xs font-bold text-[#0088CC] hover:underline">
                  <i class="fa-brands fa-telegram text-base"></i> Telegram Support
                </a>
              </div>

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

            <!-- Slide-out Mobile Menu Drawer -->
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
                    <i class="fa-solid fa-terminal"></i> Console
                  </button>
                  <button @click="navigateMobile('leaderboard')" :class="currentTab === 'leaderboard' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-trophy"></i> Leaderboard
                  </button>
                  <button @click="navigateMobile('payment')" :class="currentTab === 'payment' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-wallet"></i> Payment & Withdraw
                  </button>
                  <button @click="navigateMobile('profile')" :class="currentTab === 'profile' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'hover:bg-slate-50 text-slate-600'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                    <i class="fa-solid fa-user"></i> Profile Details
                  </button>
                </nav>

                <div class="p-4 border-t border-slate-100 bg-slate-50 text-xs font-bold flex flex-col gap-3">
                  <a href="https://t.me/MinoXSupport0" target="_blank" class="flex items-center gap-2 text-[#0088CC] hover:underline">
                    <i class="fa-brands fa-telegram text-base"></i> Telegram Support
                  </a>
                  <div class="flex items-center justify-between border-t pt-3">
                    <span class="text-slate-800">{{ user?.name || 'User' }}</span>
                    <button @click="signOut" class="text-rose-500 hover:text-rose-700"><i class="fa-solid fa-right-from-bracket"></i> LOGOUT</button>
                  </div>
                </div>
              </aside>
            </transition>
            
            <!-- Mobile Menu Backdrop -->
            <div v-if="mobileMenuOpen" @click="mobileMenuOpen = false" class="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 md:hidden"></div>

            <!-- Main Content Area -->
            <main class="flex-1 p-4 md:p-8 space-y-6 overflow-y-auto">
              
              <header class="flex justify-between items-center border-b border-slate-200 pb-4">
                <div class="flex items-center gap-3">
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
                        <p class="text-[10px] text-slate-400 font-bold">Base OTP Rate</p>
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

                <!-- SUMMARY CARD -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <h3 class="font-extrabold text-xs text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
                    <i class="fa-solid fa-square-poll-vertical text-[#0088CC]"></i> WORK SUMMARY
                  </h3>
                  <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div class="bg-slate-50 p-3 rounded-xl border border-slate-100">
                      <span class="text-[9px] text-slate-400 font-bold block uppercase">All Numbers</span>
                      <span class="text-base font-black text-slate-800 block mt-1">{{ allocations.length }}</span>
                    </div>
                    <div class="bg-amber-50/50 p-3 rounded-xl border border-amber-100">
                      <span class="text-[9px] text-amber-600 font-bold block uppercase">Active (Pending)</span>
                      <span class="text-base font-black text-amber-600 block mt-1">{{ allocations.filter(a => a.status === 'active').length }}</span>
                    </div>
                    <div class="bg-emerald-50/50 p-3 rounded-xl border border-emerald-100">
                      <span class="text-[9px] text-emerald-600 font-bold block uppercase">Success OTP</span>
                      <span class="text-base font-black text-emerald-600 block mt-1">{{ allocations.filter(a => a.status === 'completed').length }}</span>
                    </div>
                    <div class="bg-rose-50/50 p-3 rounded-xl border border-rose-100">
                      <span class="text-[9px] text-rose-600 font-bold block uppercase">Failed / Expired</span>
                      <span class="text-base font-black text-rose-600 block mt-1">{{ allocations.filter(a => a.status === 'expired').length }}</span>
                    </div>
                  </div>
                </div>

                <!-- HELP DESK BANNER -->
                <div class="bg-gradient-to-r from-[#0088CC]/10 to-[#0088CC]/5 p-4 rounded-2xl border border-[#0088CC]/20 flex justify-between items-center">
                  <div class="space-y-1">
                    <span class="text-[9px] text-[#0088CC] font-black uppercase tracking-wider block">SUPPORT & HELP DESK</span>
                    <p class="text-xs text-slate-700 font-semibold leading-relaxed">Connect directly with Telegram Support for manual deposits and inquiries.</p>
                  </div>
                  <a href="https://t.me/MinoXSupport0" target="_blank" class="bg-[#0088CC] hover:bg-[#0077B5] text-white text-xs font-bold px-3 py-2 rounded-xl flex items-center gap-1 shrink-0 transition shadow-sm active:scale-95">
                    <i class="fa-brands fa-telegram text-sm"></i> Telegram Support
                  </a>
                </div>

                <!-- Latest OTP Reports -->
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
                        <span class="font-bold text-emerald-600 text-sm font-mono">{{ log.otp_code }}</span>
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

                  <!-- Segmented Numbers View -->
                  <div v-else class="space-y-3">
                    <div v-for="alloc in paginatedAllocations" :key="alloc.createdAt" class="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-xs hover:shadow-sm hover:border-slate-300 transition">
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
                            <div @click="copyFullSms(alloc.message, alloc.otp)" class="bg-emerald-50 hover:bg-emerald-100 border-2 border-emerald-400 p-2 rounded-xl text-emerald-800 text-center cursor-pointer active:scale-95 transition flex items-center justify-between gap-2 group min-w-0 shadow-xs">
                              <div class="text-left truncate">
                                <span class="text-[8px] text-emerald-600 font-black uppercase tracking-tight block">OTP Code</span>
                                <span class="text-xs md:text-base font-extrabold text-emerald-900 tracking-widest block truncate font-mono">
                                  {{ displayOtp(alloc) }}
                                </span>
                              </div>
                              <i class="fa-regular fa-copy text-xs text-emerald-500 group-hover:text-emerald-700 shrink-0"></i>
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

              <!-- ==================== SECTION 3: Console ==================== -->
              <div v-if="currentTab === 'console'" class="space-y-6">
                
                <div v-if="topApps.list.length > 0" class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-6">
                  <div class="flex items-center gap-2 border-b pb-2">
                    <i class="fa-solid fa-chart-simple text-[#0088CC] text-md"></i>
                    <h3 class="font-extrabold text-xs text-slate-400 uppercase tracking-widest">Top Apps</h3>
                  </div>

                  <!-- Vertical Columns Layout Chart -->
                  <div class="relative h-56 border border-slate-100 bg-slate-50/30 rounded-2xl flex items-end justify-around pb-4 pt-8 px-6 gap-6">
                    <div class="absolute inset-x-0 top-0 h-full flex flex-col justify-between pointer-events-none select-none opacity-30 p-4">
                      <div class="border-t border-dashed border-slate-200 w-full h-0"></div>
                      <div class="border-t border-dashed border-slate-200 w-full h-0"></div>
                      <div class="border-t border-dashed border-slate-200 w-full h-0"></div>
                      <div class="border-t border-dashed border-slate-200 w-full h-0"></div>
                    </div>

                    <div v-for="(appItem, idx) in topApps.list" :key="appItem.name" class="relative flex flex-col items-center group w-16 z-10 h-full justify-end">
                      <span class="bg-slate-800 text-white text-[10px] px-2 py-0.5 rounded font-black mb-2 shadow-xs">
                        {{ appItem.count }}
                      </span>
                      <div :style="{ height: Math.max(10, appItem.percentage) + '%' }" :class="barColors[idx % 4]" class="w-8 rounded-t-xl transition-all duration-500 shadow-sm relative flex items-end justify-center">
                      </div>
                      <span class="text-[10px] font-black text-slate-500 mt-2 truncate max-w-full block uppercase tracking-wider">{{ appItem.name }}</span>
                    </div>
                  </div>

                  <div class="space-y-2.5">
                    <div v-for="(appItem, idx) in topApps.list" :key="appItem.name" class="flex justify-between items-center text-xs font-semibold">
                      <div class="flex items-center gap-2">
                        <span :class="dotColors[idx % 4]" class="h-3 w-3 rounded-full shrink-0"></span>
                        <span class="text-slate-800 font-bold">{{ appItem.name }}</span>
                      </div>
                      <div class="flex items-center gap-3">
                        <span class="text-slate-800 font-black">{{ appItem.count }}</span>
                        <span class="text-slate-400 font-bold w-10 text-right">{{ appItem.percentage }}%</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs flex justify-between items-center">
                  <div>
                    <div class="flex items-center gap-2">
                      <i class="fa-solid fa-satellite-dish text-[#0088CC] text-lg animate-pulse"></i>
                      <h2 class="text-md font-black text-slate-900">Console Logs</h2>
                    </div>
                    <p class="text-[10px] text-slate-400 font-medium mt-1">Limited to 150 items. New intercepted logs slide gracefully on top.</p>
                  </div>
                  <span class="bg-slate-50 text-slate-600 text-[10px] font-bold px-3 py-1.5 rounded-full select-none border">
                    {{ liveLogs.length }} / 150 Active Logs
                  </span>
                </div>

                <div class="space-y-3">
                  <div v-if="liveLogs.length === 0" class="p-12 text-slate-400 text-center font-semibold bg-white border rounded-3xl text-xs">Initializing global signal tracker...</div>
                  
                  <div v-else class="space-y-2.5">
                    <div v-for="log in liveLogs" :key="log.range + '_' + log.service + '_' + log.time" @click="copyToClipboard(log.range)" class="bg-white p-4 rounded-2xl border border-slate-200 shadow-xs cursor-pointer hover:border-[#0088CC] hover:bg-slate-50/50 transition duration-300 active:scale-[0.99] space-y-2">
                      <div class="flex justify-between items-start border-b border-slate-100 pb-1.5">
                        <div>
                          <span class="text-xs font-black text-[#0088CC] uppercase tracking-wide block">
                            {{ log.service }}
                          </span>
                          <span class="text-[10px] font-bold text-slate-500 block mt-0.5">
                            {{ log.range }}
                          </span>
                        </div>
                        <span class="bg-slate-100 text-slate-500 text-[9px] font-bold px-2 py-0.5 rounded uppercase">
                          {{ log.country }}
                        </span>
                      </div>
                      <div class="space-y-1">
                        <p class="font-mono font-bold text-slate-800 text-[11px] leading-tight break-words mt-1">
                          {{ log.message }}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ==================== SECTION 4: Leaderboard ==================== -->
              <div v-if="currentTab === 'leaderboard'" class="space-y-6">
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs">
                  <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                    <div>
                      <div class="flex items-center gap-2">
                        <i class="fa-solid fa-trophy text-amber-500 text-lg"></i>
                        <h2 class="text-md font-black text-slate-900">TOP WORKERS LEADERBOARD</h2>
                      </div>
                      <p class="text-[10px] text-slate-400 font-medium mt-1">Real-time work ranks based on completed OTP codes verified securely.</p>
                    </div>
                    <span class="text-[10px] text-slate-500 font-bold uppercase tracking-tight italic bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-full shrink-0 flex items-center gap-1.5">
                      <i class="fa-regular fa-clock"></i> Restarts every 25 Hours
                    </span>
                  </div>

                  <div class="flex gap-2 text-xs font-black mt-5">
                    <button @click="leaderboardTab = 'today'" :class="leaderboardTab === 'today' ? 'bg-[#0088CC] text-white' : 'bg-slate-50 text-slate-500 hover:bg-slate-100'" class="px-4 py-2 rounded-xl transition">Today (25H)</button>
                    <button @click="leaderboardTab = 'weekly'" :class="leaderboardTab === 'weekly' ? 'bg-[#0088CC] text-white' : 'bg-slate-50 text-slate-500 hover:bg-slate-100'" class="px-4 py-2 rounded-xl transition">Weekend</button>
                    <button @click="leaderboardTab = 'lifetime'" :class="leaderboardTab === 'lifetime' ? 'bg-[#0088CC] text-white' : 'bg-slate-50 text-slate-500 hover:bg-slate-100'" class="px-4 py-2 rounded-xl transition">Lifetime</button>
                  </div>

                  <div class="space-y-3 mt-4">
                    <div v-for="(worker, idx) in leaderboardData[leaderboardTab]" :key="idx" class="flex justify-between items-center bg-slate-50/50 p-4 rounded-2xl border border-slate-200/60 text-xs">
                      <div class="flex items-center gap-3">
                        <span class="font-black text-xs h-7 w-7 rounded-full flex items-center justify-center shrink-0 border shadow-xs" :class="idx === 0 ? 'bg-amber-100 text-amber-700 border-amber-200' : idx === 1 ? 'bg-slate-200 text-slate-700 border-slate-300' : 'bg-orange-100 text-orange-700 border-orange-200'">
                          #{{ idx + 1 }}
                        </span>
                        <div>
                          <span class="font-extrabold text-slate-800 text-sm block">{{ worker.name }}</span>
                          <span class="text-[10px] text-slate-400 block font-semibold">{{ worker.id_code }}</span>
                        </div>
                      </div>
                      <span class="font-black text-[#0088CC] text-sm bg-white border border-slate-200 px-3 py-1 rounded-full shadow-2xs">
                        {{ worker.count }} Successful OTPs
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ==================== SECTION 5: Payment & Withdraw ==================== -->
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

              <!-- ==================== SECTION 6: Profile Details ==================== -->
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
                      <div v-if="profile && profile.api_key" class="space-y-2">
                        <p class="text-slate-500">API Access Key:</p>
                        
                        <!-- If APPROVED: Show actual API key -->
                        <div v-if="profile.api_key_approved" class="flex flex-col gap-2">
                          <span class="text-slate-800 font-mono text-[10px] bg-slate-50 px-3 py-2 rounded border break-all select-all font-semibold">
                            {{ profile.api_key }}
                          </span>
                          <span class="text-emerald-600 text-[10px] font-bold">
                            <i class="fa-solid fa-circle-check"></i> API Key Approved (Unlimited access active)
                          </span>
                          <button @click="copyToClipboard(profile.api_key)" class="bg-[#0088CC]/10 text-[#0088CC] font-bold px-3 py-1.5 rounded-xl text-[10px] hover:bg-[#0088CC]/20 transition flex items-center gap-1 w-max">
                            Copy API Key <i class="fa-solid fa-copy"></i>
                          </button>
                        </div>
                        
                        <!-- If NOT APPROVED: Hide actual API key and show 'API Key is disabled' -->
                        <div v-else class="flex flex-col gap-2">
                          <span class="text-rose-600 font-mono text-[11px] bg-rose-50 px-3 py-2 rounded border border-rose-200 font-black">
                            API Key is disabled (Pending Admin Approval)
                          </span>
                          <span class="text-amber-600 text-[10px] font-bold animate-pulse">
                            <i class="fa-solid fa-clock"></i> API Key Pending Admin Approval (12s cooldown applies)
                          </span>
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

              <!-- ==================== SECTION 7: API Docs & Test Lab ==================== -->
              <div v-if="currentTab === 'api-docs'" class="space-y-6">
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <div class="flex items-center gap-2">
                    <i class="fa-solid fa-code text-[#0088CC] text-lg"></i>
                    <h2 class="text-md font-black text-slate-900">Mino API Documentation & Test Lab</h2>
                  </div>
                  <div class="p-4 bg-indigo-50 border border-indigo-200 rounded-2xl font-semibold text-xs leading-relaxed text-indigo-900">
                    <span class="text-[9px] uppercase font-black text-indigo-500 block mb-1">GLOBAL SERVER BASE PATH</span>
                    <strong class="font-mono text-sm tracking-wide select-all">{{ apiBaseUrl }}</strong>
                  </div>
                </div>

                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-5">
                  <h3 class="font-extrabold text-xs text-slate-400 uppercase tracking-widest border-b pb-2">API Documentation Schemas</h3>
                  
                  <div class="space-y-6">
                    <!-- POST Booking -->
                    <div class="space-y-2">
                      <div class="flex items-center gap-2">
                        <span class="bg-rose-600 text-white text-[9px] font-black px-2 py-0.5 rounded">POST/GET</span>
                        <h4 class="text-xs font-black text-slate-800">1. Number Booking Endpoint</h4>
                      </div>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border">
                        {{ apiBaseUrl }}/@public/api/getnum?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}&rid=2250789XXX&national=1&remove_plus=1
                      </div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase mt-2">Example JSON Response:</p>
                      <pre class="bg-slate-900 text-emerald-400 p-3 rounded-xl text-[9px] font-mono overflow-x-auto leading-relaxed border select-all">{
  "status": "success",
  "number": "+2250789538803",
  "country": "Ivory Coast",
  "operator": "Orange"
}</pre>
                    </div>

                    <!-- GET Access status -->
                    <div class="space-y-2 border-t pt-4">
                      <div class="flex items-center gap-2">
                        <span class="bg-emerald-600 text-white text-[9px] font-black px-2 py-0.5 rounded">GET</span>
                        <h4 class="text-xs font-black text-slate-800">2. Client Access Status</h4>
                      </div>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border">
                        {{ apiBaseUrl }}/@public/api/liveaccess?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}
                      </div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase mt-2">Example JSON Response:</p>
                      <pre class="bg-slate-900 text-emerald-400 p-3 rounded-xl text-[9px] font-mono overflow-x-auto leading-relaxed border select-all">{
  "status": "success",
  "message": "API credentials validated successfully",
  "client": {
    "uid": "usr_9fbf51db...",
    "name": "Minhaz Sarkae",
    "id_code": "MINO-8821",
    "balance": 6.65,
    "otp_rate": 0.40
  }
}</pre>
                    </div>

                    <!-- GET Success logs -->
                    <div class="space-y-2 border-t pt-4">
                      <div class="flex items-center gap-2">
                        <span class="bg-emerald-600 text-white text-[9px] font-black px-2 py-0.5 rounded">GET</span>
                        <h4 class="text-xs font-black text-slate-800">3. Success OTP logs</h4>
                      </div>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border">
                        {{ apiBaseUrl }}/@public/api/success-otp?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}
                      </div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase mt-2">Example JSON Response:</p>
                      <pre class="bg-slate-900 text-emerald-400 p-3 rounded-xl text-[9px] font-mono overflow-x-auto leading-relaxed border select-all">{
  "status": "success",
  "data": [
    {
      "number": "+2250789538803",
      "service": "facebook",
      "otp_code": "972450",
      "message": "Your Facebook code is 972450",
      "revenue_earned": 0.40,
      "created_at": "2026-06-22T10:10:05.123Z"
    }
  ]
}</pre>
                    </div>

                    <!-- GET Console tracks -->
                    <div class="space-y-2 border-t pt-4">
                      <div class="flex items-center gap-2">
                        <span class="bg-emerald-600 text-white text-[9px] font-black px-2 py-0.5 rounded">GET</span>
                        <h4 class="text-xs font-black text-slate-800">4. Console Tracker signal stream</h4>
                      </div>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border">
                        {{ apiBaseUrl }}/@public/api/console?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}
                      </div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase mt-2">Example JSON Response:</p>
                      <pre class="bg-slate-900 text-emerald-400 p-4 rounded-2xl text-[9px] font-mono overflow-x-auto leading-relaxed border select-all">{
  "status": "success",
  "data": [
    {
      "range": "2250789XXX",
      "service": "FACEBOOK",
      "message": "Signal intercepted on range 2250789XXX for FACEBOOK",
      "time": 1782099243663,
      "country": "Ivory Coast"
    }
  ]
}</pre>
                    </div>

                    <!-- GET/POST Check Status -->
                    <div class="space-y-2 border-t pt-4">
                      <div class="flex items-center gap-2">
                        <span class="bg-indigo-600 text-white text-[9px] font-black px-2 py-0.5 rounded">GET/POST</span>
                        <h4 class="text-xs font-black text-slate-800">5. Check Number Status (Bot Friendly API)</h4>
                      </div>
                      <div class="bg-slate-50 p-2.5 rounded-xl font-mono text-[10px] text-slate-700 select-all overflow-x-auto border">
                        {{ apiBaseUrl }}/@public/api/check?api_key={{ profile?.api_key || 'YOUR_API_KEY' }}&number=+2250789538803
                      </div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase mt-2">Example JSON Response:</p>
                      <pre class="bg-slate-900 text-emerald-400 p-3 rounded-xl text-[9px] font-mono overflow-x-auto leading-relaxed border select-all">{
  "status": "success",
  "number": "+2250789538803",
  "allocation_status": "completed",
  "otp_code": "972450",
  "full_sms": "Your Facebook code is 972450",
  "created_at": "2026-06-22T10:10:05.123Z"
}</pre>
                    </div>

                  </div>
                </div>

                <!-- Live API Tester -->
                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs space-y-4">
                  <h3 class="text-xs font-black text-slate-800 flex items-center gap-2">
                    <i class="fa-solid fa-flask text-[#0088CC]"></i> Live API Tester
                  </h3>
                  
                  <div class="grid sm:grid-cols-3 gap-3 text-xs font-bold">
                    <div>
                      <label class="text-slate-400">Select Target Endpoint</label>
                      <select v-model="selectedTestApi" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl font-semibold outline-none focus:border-[#0088CC]">
                        <option value="getnum">getnum (Allocate Number - POST/GET)</option>
                        <option value="liveaccess">liveaccess (Check Access Status - GET)</option>
                        <option value="success-otp">success-otp (Success logs - GET)</option>
                        <option value="console">console (Live Stream Logs - GET)</option>
                        <option value="check">check (Status Check - GET/POST)</option>
                      </select>
                    </div>

                    <div v-if="selectedTestApi === 'getnum' || selectedTestApi === 'check'">
                      <label class="text-slate-400">{{ selectedTestApi === 'getnum' ? 'Target Range ID' : 'Target Number' }}</label>
                      <input type="text" v-model="testRange" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl font-mono" />
                    </div>

                    <div class="flex items-end" :class="selectedTestApi !== 'getnum' && selectedTestApi !== 'check' ? 'col-span-2' : ''">
                      <button @click="runLiveApiTest" :disabled="testApiLoading" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-3 rounded-xl transition flex items-center justify-center gap-1.5 disabled:bg-slate-200">
                        <i v-if="testApiLoading" class="fa-solid fa-spinner animate-spin"></i>
                        <span>Execute API Test</span>
                      </button>
                    </div>

                  </div>

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
            
            let generalTimer = null;
            let consoleTimer = null;

            const selectedTestApi = ref('getnum');
            const testRange = ref('2250789XXX');
            const testApiLoading = ref(false);
            const testApiResponse = ref(null);
            const apiBaseUrl = ref(window.location.origin);

            const barColors = ['bg-blue-500', 'bg-purple-500', 'bg-amber-500', 'bg-emerald-500'];
            const dotColors = ['bg-blue-500', 'bg-purple-500', 'bg-amber-500', 'bg-emerald-500'];

            const leaderboardTab = ref('today');
            const leaderboardData = ref({ today: [], weekly: [], lifetime: [] });

            const withdrawAmount = ref('');
            const withdrawMethod = ref('TRC20');

            const serviceRates = ref({
              facebook: { rate: 0.40, status: 'ON' },
              instagram: { rate: 0.40, status: 'ON' },
              whatsapp: { rate: 0.00, status: 'OFF' },
              telegram: { rate: 0.00, status: 'OFF' },
              google: { rate: 0.40, status: 'ON' },
              generic: { rate: 0.40, status: 'ON' }
            });

            // Fallback parsing engine for extracting digits in historical/bugged database records
            const displayOtp = (alloc) => {
              if (!alloc.otp) return 'N/A';
              if (alloc.otp === 'SUCCESS' && alloc.message) {
                const match = alloc.message.match(/\\b\\d{4,9}\\b/);
                if (match) return match[0];
                const anyDigits = alloc.message.match(/\\d+/g);
                if (anyDigits) {
                  const longest = anyDigits.reduce((a, b) => a.length > b.length ? a : b);
                  return longest.slice(0, 9);
                }
              }
              return alloc.otp;
            };

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

            // Custom click-and-copy behavior supporting fallback variables
            const copyFullSms = (messageText, fallbackOtp) => {
              const textToCopy = messageText || fallbackOtp || "";
              if (!textToCopy) return;
              navigator.clipboard.writeText(textToCopy);
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
              fetchGeneralData();
              fetchConsoleData();
              generalTimer = setInterval(fetchGeneralData, 5000);
              consoleTimer = setInterval(fetchConsoleData, 2000); 
            };

            const stopPolling = () => {
              if (generalTimer) {
                clearInterval(generalTimer);
                generalTimer = null;
              }
              if (consoleTimer) {
                clearInterval(consoleTimer);
                consoleTimer = null;
              }
            };

            const mergeLogs = (newLogs) => {
              newLogs.forEach(newLog => {
                const key = `${newLog.range}_${newLog.service}_${newLog.time}`;
                const exists = liveLogs.value.some(existingLog => 
                  `${existingLog.range}_${existingLog.service}_${existingLog.time}` === key
                );
                if (!exists) {
                  liveLogs.value.unshift(newLog);
                }
              });

              liveLogs.value.sort((a, b) => b.time - a.time);

              if (liveLogs.value.length > 150) {
                liveLogs.value = liveLogs.value.slice(0, 150);
              }
            };

            const topApps = computed(() => {
              const counts = {};
              let total = 0;
              liveLogs.value.forEach(log => {
                const serviceName = log.service || 'Global';
                counts[serviceName] = (counts[serviceName] || 0) + 1;
                total++;
              });
              
              const list = Object.keys(counts).map(key => {
                return {
                  name: key,
                  count: counts[key],
                  percentage: total > 0 ? Math.round((counts[key] / total) * 100) : 0
                };
              });
              
              list.sort((a, b) => b.count - a.count);
              return { list: list.slice(0, 4), total };
            });

            const fetchConsoleData = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!token) return;
              try {
                const consoleRes = await fetch('/api/v1/live-console', {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                const consoleData = await consoleRes.json();
                if (consoleData.status === 'success') {
                  mergeLogs(consoleData.data);
                }
              } catch (e) {
                console.log("VoltxSMS Console Sync Error:", e);
              }
            };

            const fetchGeneralData = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!token) {
                userLoaded.value = true;
                return;
              }

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

              if (profile.value) {
                try {
                  const otpRes = await fetch('/api/v1/success-otp?api_key=' + (profile.value.api_key || ''), {
                    headers: { 'Authorization': `Bearer ${token}` }
                  });
                  const otpData = await otpRes.json();
                  if (otpData.status === 'success') {
                    successOtps.value = otpData.data;
                  }
                } catch (e) {}
              }

              try {
                const boardRes = await fetch('/api/v1/leaderboard', {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                const boardData = await boardRes.json();
                if (boardData.status === 'success') {
                  leaderboardData.value.today = boardData.today;
                  leaderboardData.value.weekly = boardData.weekly;
                  leaderboardData.value.lifetime = boardData.lifetime;
                }
              } catch (e) {}

              try {
                const ratesRes = await fetch('/api/v1/user/service-rates');
                const ratesData = await ratesRes.json();
                if (ratesData.status === 'success') {
                  serviceRates.value = ratesData.rates;
                }
              } catch (e) {}
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
                  fetchGeneralData();
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
                  triggerToast(data.message);
                  fetchGeneralData();
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
                  fetchGeneralData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("An error occurred while submitting withdrawal request.");
              }
            };

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
                  const postRes = await fetch(`/@public/api/getnum`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      api_key: profile.value.api_key,
                      rid: testRange.value,
                      national: 1,
                      remove_plus: 1
                    })
                  });
                  const postData = await postRes.json();
                  testApiResponse.value = JSON.stringify(postData, null, 2);
                  testApiLoading.value = false;
                  return;
                } else if (selectedTestApi.value === 'liveaccess') {
                  url = `/@public/api/liveaccess?api_key=${profile.value.api_key}`;
                } else if (selectedTestApi.value === 'success-otp') {
                  url = `/@public/api/success-otp?api_key=${profile.value.api_key}`;
                } else if (selectedTestApi.value === 'console') {
                  url = `/@public/api/console?api_key=${profile.value.api_key}`;
                } else if (selectedTestApi.value === 'check') {
                  url = `/@public/api/check?api_key=${profile.value.api_key}&number=${testRange.value}`;
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
                  if (data.number) {
                    copyToClipboard(data.number);
                  }
                  fetchGeneralData(); 
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
              handleAuth, signOut, handleGetNumber, formatTime, formatTimestamp, displayOtp,
              apiGenLoading, handleGenerateApiKey, selectedTestApi, runLiveApiTest, testRange, testApiLoading, testApiResponse, apiBaseUrl,
              barColors, dotColors, topApps, leaderboardTab, leaderboardData, withdrawAmount, withdrawMethod, submitWithdrawal, serviceRates
            };
          }
        }).mount('#app');
      </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype='text/html')

# =========================================================================
# Master Admin Panel UI (Fixed Loading early return spinner bug)
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
      <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
      <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
      <script src="https://cdn.tailwindcss.com"></script>
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
          <div v-if="toast" class="fixed top-5 left-1/2 -translate-x-1/2 bg-[#0088CC] text-white font-black text-xs px-5 py-3 rounded-2xl shadow-xl z-[9999] transition animate-bounce">
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
                  <input type="password" required v-model="password" class="w-full mt-1.5 p-3.5 bg-slate-50 border-rose-600 transition outline-none" />
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

              <div class="p-4 border-t border-slate-800 flex items-center justify-between bg-slate-955 text-xs font-bold">
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
                  <input type="text" v-model="searchQuery" placeholder="Search users by name, email..." class="w-full sm:w-80 p-3 bg-white border rounded-2xl text-xs font-semibold outline-none focus:border-rose-600" />
                  
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
                          <th class="p-4">API Key Status</th>
                          <th class="p-4">Status</th>
                          <th class="p-4 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-slate-100 font-semibold text-slate-700">
                        <tr v-if="filteredUsers.length === 0">
                          <td colspan="7" class="p-8 text-center text-slate-400 font-bold">No users match your criteria.</td>
                        </tr>
                        <tr v-else-if="filteredUsers" v-for="u in filteredUsers" :key="u.uid" class="hover:bg-slate-50/50 transition">
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
                          <td class="p-4 font-black">
                            <span v-if="u.api_key_approved" class="text-emerald-600 text-[10px] font-black uppercase"><i class="fa-solid fa-check-double"></i> Approved</span>
                            <span v-else-if="u.api_key" class="text-amber-600 text-[10px] font-black uppercase animate-pulse"><i class="fa-solid fa-circle-question"></i> Pending Approve</span>
                            <span v-else class="text-slate-400 text-[10px] font-bold">No Key Generated</span>
                          </td>
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
                        <label class="text-slate-400">API Key Approved Status</label>
                        <select v-model="editUser.api_key_approved" class="w-full mt-1.5 p-3 bg-slate-50 border rounded-xl text-sm outline-none focus:border-rose-600">
                          <option :value="true">Approved (Active Key)</option>
                          <option :value="false">Pending Approval (Disabled)</option>
                        </select>
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
                            <button v-if="wd.status === 'pending'" @click="processWithdrawal(wd.id, 'approved')" class="bg-[#0088CC] text-white text-[10px] font-black px-3 py-1.5 rounded-xl transition">Approve</button>
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
                          <td class="p-4 font-black text-emerald-600 text-sm font-mono">{{ log.otpCode }}</td>
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
                
                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-400 uppercase tracking-widest flex items-center gap-2">
                    <i class="fa-solid fa-coins text-rose-600"></i> Service OTP Payout & Control Status Configuration (৳)
                  </h3>
                  <p class="text-[10px] text-slate-400 font-semibold leading-relaxed">
                    Configure the payout rate and active status (ON/OFF) for each service. If a service status is toggled to OFF, users will not receive any balance reward upon OTP hits on that service.
                  </p>
                  
                  <div class="space-y-3.5">
                    <div v-for="(svcConfig, svcName) in serviceRates" :key="svcName" class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-slate-50 p-4 rounded-2xl border border-slate-150">
                      <span class="text-xs font-black uppercase text-slate-800 tracking-wide">
                        {{ svcName }}
                      </span>
                      <div class="flex items-center gap-3 w-full sm:w-auto">
                        <div class="flex items-center bg-white border rounded-xl px-2.5 py-1">
                          <span class="text-[10px] font-bold text-slate-400 mr-1.5">৳</span>
                          <input type="number" step="0.01" v-model="svcConfig.rate" class="w-16 text-xs font-black text-slate-800 outline-none" placeholder="0.40" />
                        </div>
                        <button @click="svcConfig.status = (svcConfig.status === 'ON' ? 'OFF' : 'ON')" :class="svcConfig.status === 'ON' ? 'bg-emerald-600 text-white border-emerald-700' : 'bg-rose-600 text-white border-rose-700'" class="px-3.5 py-1.5 rounded-xl text-[10px] font-black border transition select-none tracking-wider">
                          {{ svcConfig.status === 'ON' ? 'ACTIVE (ON)' : 'MUTED (OFF)' }}
                        </button>
                      </div>
                    </div>
                  </div>

                  <button @click="saveServiceRates" class="bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold px-5 py-2.5 rounded-xl transition shadow-xs active:scale-95">
                    Save Service Controls
                  </button>
                </div>

                <div class="bg-white p-6 rounded-3xl border shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-400 uppercase tracking-widest flex items-center gap-2">
                    <i class="fa-solid fa-bullhorn text-rose-600"></i> Global Announcement Control Banner
                  </h3>
                  <textarea v-model="announcementInput" rows="2" placeholder="Enter notice updates..." class="w-full p-3 bg-slate-50 border rounded-xl text-xs outline-none focus:border-rose-600 font-semibold"></textarea>
                  <button @click="updateAnnouncement" class="bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold px-4 py-2.5 rounded-xl transition">
                    Publish Banner Update
                  </button>
                </div>

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
                        <li><strong>Rule 18:</strong> Signal Intercept radars mapped to VOLTX streams.</li>
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

            const serviceRates = ref({
              facebook: { rate: 0.40, status: 'ON' },
              instagram: { rate: 0.40, status: 'ON' },
              whatsapp: { rate: 0.00, status: 'OFF' },
              telegram: { rate: 0.00, status: 'OFF' },
              google: { rate: 0.40, status: 'ON' },
              generic: { rate: 0.40, status: 'ON' }
            });

            const stats = ref({
              total_users: 0,
              pending_users: 0,
              total_allocations: 0,
              total_otps: 0,
              total_withdrawals: 0,
              maintenance_mode: false,
              announcement: ''
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
                  triggerToast("Portal Access Granted! 🔓");
                  fetchDashboardData();
                } else {
                  alert(data.message || 'Invalid admin credentials entered.');
                }
              } catch (e) {
                alert("Server connection failed.");
              }
              authLoading.value = false;
            };

            const logOut = () => {
              localStorage.removeItem('mino_admin_token');
              adminToken.value = '';
              triggerToast("Logged out securely. 🔒");
            };

            // High-Performance Consolidated Admin UI fetch
            const fetchDashboardData = async () => {
              if (!adminToken.value) {
                loading.value = false;
                return;
              }
              try {
                const res = await fetch('/api/v1/admin/dashboard-all', {
                  headers: { 'Authorization': `Bearer ${adminToken.value}` }
                });
                if (res.status === 401) { 
                  logOut(); 
                  loading.value = false;
                  return; 
                }
                const data = await res.json();
                if (data.status === 'success') {
                  stats.value = data.stats;
                  users.value = data.users;
                  allocations.value = data.allocations;
                  otpLogs.value = data.otp_logs;
                  withdrawals.value = data.withdrawals;
                  serviceRates.value = data.rates;
                  announcementInput.value = data.stats.announcement || '';
                }
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
                  triggerToast(`Maintenance mode turned ${data.maintenance_mode ? 'ON' : 'OFF'}. 🛠️`);
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
                  triggerToast("Global notice updated! 📢");
                }
              } catch (e) {}
            };

            const saveServiceRates = async () => {
              try {
                const res = await fetch('/api/v1/admin/settings/service-rates', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${adminToken.value}`
                  },
                  body: JSON.stringify({ rates: serviceRates.value })
                });
                const data = await res.json();
                if (data.status === 'success') {
                  triggerToast("Service payout rates successfully updated! 💰");
                  fetchDashboardData();
                } else {
                  alert(data.message);
                }
              } catch (e) {
                alert("Failed to update service rates.");
              }
            };

            const processWithdrawal = async (id, action) => {
              if (!confirm("Are you sure you want to change this withdrawal request status to " + action + "?")) return;
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
                  triggerToast("Withdrawal request has been marked as " + action);
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
                  downloadAnchor.setAttribute("download", "mino_backup_" + new Date().toISOString().slice(0,10) + ".json");
                  document.body.appendChild(downloadAnchor);
                  downloadAnchor.click();
                  downloadAnchor.remove();
                  triggerToast("Database JSON export download initiated! 📥");
                }
              } catch (e) {}
            };

            const exportUsersToCSV = () => {
              let csvContent = "data:text/csv;charset=utf-8,";
              csvContent += "Name,Email,Balance,Status,OTP Rate\\n";
              
              users.value.forEach(u => {
                csvContent += '"' + u.name + '","' + u.email + '",' + u.balance + ',"' + u.status + '",' + u.otp_rate + '\\n';
              });

              const encodedUri = encodeURI(csvContent);
              const link = document.createElement("a");
              link.setAttribute("href", encodedUri);
              link.setAttribute("download", "mino_users_export_" + new Date().toISOString().slice(0,10) + ".csv");
              document.body.appendChild(link);
              link.click();
              link.remove();
              triggerToast("User database exported to CSV! 📊");
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
                  triggerToast("User account details successfully updated! ✅");
                  editUser.value = null;
                  fetchDashboardData();
                } else {
                  alert(data.message);
                }
              } catch (e) {}
            };

            const deleteUser = async (uid) => {
              if (!confirm("Are you sure you want to permanently delete this user account?")) return;
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
                  triggerToast("User permanently removed. 🗑️");
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
              serviceRates, saveServiceRates,
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