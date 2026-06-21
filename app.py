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
FIREBASE_DB_URL = "https://all-panel-support-default-rtdb.firebaseio.com/"

CRED_DICT = {
  "type": "service_account",
  "project_id": "all-panel-support",
  "private_key_id": "f482e69eaee23c8be49b2394631ac36dd9201617",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDLp7LfbvuJaHBJ\nfqr54VUXwa35OYJq+7MnrjexU2+Cye3figOn/GgSGEKbSruDP2BD/isarRdNSShy\nB6eKphcn5/iQIfdWJx9oDdbK+VQrF7HfmvN3JVdoKLIOUCLlcLGGO2RuFuLFMhhh\ns+Iu8kX7TBFafVwP796+qrTNc4r4LqbbjB3lgfiMvWd5jUhbuWGJ8N8wd1mM/S9q\ndzTSx/w6yPAsKwRWySUHCI0o1S6E1RiFPLJDeLpp5wrzqn5IfzbqjAs9eh4HNAP5\nov4F5fhhXVp5b0xmNXcn7CfnIkX86VRC1mri4MO2LKV6Ld+A7rC1LG/fSDv1dDNk\nXZ7//821AgMBAAECggEAALQeMwA/aA4KEJrv13KpmFjVM3P5KR+gUr4Fl7woebdz\nC1oUS/zcKtnWGxK9m0UOswAaYS/MEY/ejvxLSM2XmA3zXCNzPGM2DCY7bH1C3EOV\n8VDn+pdQr2halcroP/TXzCqsMhGBVuSRfymVBGFWZWPxzbylTYcgNMuYBHtbys00\nNouHuM3+Ok1A4xa0XBaNMW3QKXFoPpoxCYEvZf6ZQoJwj3SyNBbXyVuNDSAExy6a\nFpfUZaWWdkzueeu4W/RelWbLiicGo0NQQJpVT4WtYj9Y5aTDxuD+GNBuANLK6pUO\n5ZDCiiIEXxyWodOiB40n1DECL4o3txppd7ZERAodWQKBgQDvKeq07AFAEfJ56JxU\nOXlPK4GhKR7kzlYDwDFl3ges5qCsg8PaamlfSCe+ezDmLNFrcwzhW/D32BXU67WG\n3KSkWGt3xS+TKxCCzHDnsOiIRzHuWM3vWkcSxcPiiEOD+zUzJP6OGAvJQpSgUpAQ\n3llXXG4+v+m3xSN/ZOez+6Zt2QKBgQDZ/d0IfXPertMBh/sX++iBMgyVdZnSfAQy\nssiylKYEZPxfSeQ0P2zSPSFbn4YNgtUbj5ghZW1xehly4HHGsxwDbKuGbrNdlvDj\n682mj2vIkTFiJnpB17Xi8/twhUK9D2UByhdv/k6dBtAu5YzSSi7IaxyNZ6b3h7QG\n3e99L3MJPQKBgQCXF3kiwXJswqnYIH8aqpCb1pV3dh4BWOV4SyQqAeIBdlYNhtTl\nmJJnUpNhQDx9PdUzt6RsfwQ137qzIBI3WA9fkEiciuNqaytsJrIxfU76QVgnBs1b\nKEJ8dpow8/sLV1mdrQJwTHqttDVnL6G6Nm5kxY0UcXO62H17jwjeaN4UyQKBgHAV\nkK3J22b3GvVhlqCZXM35DvFWO1Y3f+0Vcg4oUkhWKFFSa+zVY72hwuIaXtHZoHuA\nVKdvQFulfSpM7xNMiq3UFUmU59LKRmfama33dmL1DKA7yobKQ/JCotkTG+Kb5MKL\nx4tFBeTFWQuT6dlCXVWdhVvLnNUPSGhzeq0yVYK9AoGALaS7t6q/m39+sCigyDvZ\nW9L36TO/xtt02XrO3MwOQordHf3ovstohZRcAepf3kChYqJtoS+jTjXmdPWt38tl\n5gLDnsBJjl/vcW+2xhtPLFmIzoMtT/yTja6oI85MlsWXNX58F6Mk97OXM/i5HK8N\n3QfQiRb/u6F6f+gzT+v6JBU=\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@all-panel-support.iam.gserviceaccount.com",
  "client_id": "112981434071027857034",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40all-panel-support.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

if not firebase_admin._apps:
    cred = credentials.Certificate(CRED_DICT)
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })

# =========================================================================
# ডাটাবেজ হ্যান্ডলারস (এটমিক অপারেশন এবং কান্ট্রি প্রিফিক্স ম্যাপ)
# =========================================================================
MEMORY_DB = None

# কান্ট্রি কোড প্রিফিক্স ম্যাপ (কনসোলে দেশের নাম দেখানোর জন্য)
COUNTRY_PREFIXES = {
    "224": "Guinea",
    "225": "Ivory Coast",
    "236": "Central African Republic",
    "221": "Senegal",
    "223": "Mali",
    "226": "Burkina Faso",
    "227": "Niger",
    "228": "Togo",
    "229": "Benin",
    "237": "Cameroon",
    "241": "Gabon",
    "242": "Congo",
    "243": "DR Congo",
    "235": "Chad",
    "240": "Equatorial Guinea",
    "231": "Liberia",
    "232": "Sierra Leone",
    "233": "Ghana",
    "234": "Nigeria",
    "250": "Rwanda",
    "254": "Kenya",
    "255": "Tanzania",
    "256": "Uganda",
    "257": "Burundi",
    "261": "Madagascar",
    "269": "Comoros"
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
                v['id'] = k  # ফায়ারবেজের অনন্য কী (Key) কে অবজেক্টের আইডি হিসেবে ট্র্যাক করা হবে
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

def save_db(db_data):
    # গ্লোবাল রুট ওভাররাইট ঠেকাতে এই ফাংশনটি নিষ্ক্রিয় করা হয়েছে।
    # ডাটাবেজের সব রাইট অপারেশন এখন পারমাণবিক (Atomic) পাথে সরাসরি সম্পন্ন হয়।
    pass

# =========================================================================
# CORS এবং এন্টি-ক্যাশিং পলিসি
# =========================================================================
@app.before_request
def handle_options_preflight():
    if request.method == 'OPTIONS':
        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-MINO-API-KEY,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        return response

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-MINO-API-KEY,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ডেটটাইম ক্র্যাশ এড়ানোর জন্য নিরাপদ পার্সার
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

STEX_API_KEY = "MWF1Z0QG1DJ"
STEX_BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api"

def mask_number(number):
    if not number:
        return ''
    length = len(number)
    if length < 8:
        return number
    return f"{number[:6]}****{number[length-3:]}"

# অথেনটিকেশন মিডলওয়্যার
def get_current_user(db):
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        user = db["users"].get(token)
        if user:
            return user

    api_key = request.headers.get('X-MINO-API-KEY') or request.args.get('api_key')
    if api_key:
        for u in db["users"].values():
            if u.get('api_key') and u['api_key'] == api_key:
                return u
    return None

# =========================================================================
# রাউট ও এপিআই সমূহ
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
            'api_key': '', # প্রথম রেজিস্ট্রেশনে ফাকা থাকবে
            'balance': 0.00,
            'otp_rate': 0.40,
            'wallet_address': '', 
            'id_code': f"MINO-{secrets.randbelow(9000) + 1000}",
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        # ক্লাউডে পারমাণবিক বা এটমিক সেভ (Atomic Write)
        fb_db.reference(f'/users/{uid}').set(user_data)
        
        return jsonify({'status': 'success', 'token': uid, 'user': user_data})
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
                return jsonify({'status': 'success', 'token': uid, 'user': u})

        return jsonify({'status': 'error', 'message': 'Invalid email or password'}), 401
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/auth/me', methods=['GET'])
def get_me():
    try:
        db = load_db()
        u = get_current_user(db)
        if not u:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return jsonify({'status': 'success', 'user': u})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# এপিআই কি জেনারেট (পারমাণবিক সেভ)
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

# ওয়ালেট এড্রেস এডিট (পারমাণবিক সেভ)
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

        # GET রিকোয়েস্ট ট্রাই
        try:
            params = {
                'rid': clean_rid,
                'national': int(national),
                'remove_plus': int(remove_plus)
            }
            res = requests.get(
                f"{STEX_BASE_URL}/getnum",
                params=params,
                headers={'mauthapi': STEX_API_KEY},
                timeout=10
            )
            if res.status_code == 200:
                json_res = res.json()
                meta = json_res.get('meta', {})
                if meta.get('status') == 'ok' or meta.get('code') == 200:
                    stex_data = json_res
                else:
                    last_error = json_res.get('message') or json_res.get('msg') or last_error
        except Exception as e:
            print("GET Attempt Failed:", e)

        # POST রিকোয়েস্ট ট্রাই
        if not stex_data:
            try:
                payload = {
                    'rid': clean_rid,
                    'national': int(national),
                    'remove_plus': int(remove_plus)
                }
                res = requests.post(
                    f"{STEX_BASE_URL}/getnum",
                    json=payload,
                    headers={'mauthapi': STEX_API_KEY},
                    timeout=10
                )
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

        # এটমিক পুশ (নির্দিষ্ট পাথে ডাটা আপডেট হবে)
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

        # লাইভ ওটিপি সিঙ্ক
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
                                    # ১. ইউজারের ব্যালেন্স ক্লাউডে আপডেট করুন
                                    fb_db.reference(f'/users/{user_id}/balance').set(new_balance)
                                    
                                    # ২. ওটিপি লগ ক্লাউডে পুশ করুন
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

                                # ৩. এলোকেশনের স্ট্যাটাস ক্লাউডে আপডেট করুন
                                alloc_id = alloc.get('id')
                                if alloc_id:
                                    fb_db.reference(f'/allocated_numbers/{alloc_id}').update({
                                        'status': 'completed',
                                        'otp': otp_code,
                                        'message': message
                                    })

                                # ৪. লাইভ কনসোল ক্লাউডে পুশ করুন
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

        # মেমোরিতে থাকা এলোকেশন পুনরায় লোড করুন
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
                    # ক্লাউড অথবা প্রিফিক্স ম্যাপ থেকে কান্ট্রি নির্ধারণ
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

              <!-- ==================== সেকশন ২: নাম্বার নিন ==================== -->
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

                  <div v-else class="space-y-3">
                    <div v-for="alloc in paginatedAllocations" :key="alloc.createdAt" class="bg-white p-4 rounded-3xl border border-slate-200 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 transition hover:shadow-xs hover:border-slate-300">
                      
                      <div class="space-y-1.5 shrink-0">
                        <div @click="copyToClipboard(alloc.number)" class="flex items-center gap-1.5 cursor-pointer hover:opacity-80 active:scale-95 transition">
                          <span class="font-black text-slate-800 text-sm tracking-wider">{{ alloc.number }}</span>
                          <i class="fa-regular fa-copy text-xs text-[#0088CC]"></i>
                        </div>
                        
                        <div class="flex gap-1.5">
                          <span v-if="alloc.status === 'active'" class="bg-amber-50 text-amber-600 text-[9px] font-black px-2 py-0.5 rounded-full uppercase flex items-center gap-1">
                            <i class="fa-solid fa-spinner animate-spin text-[8px]"></i> PENDING
                          </span>
                          <span v-else-if="alloc.status === 'completed'" class="bg-emerald-100 text-emerald-800 text-[9px] font-black px-2 py-0.5 rounded-full uppercase">
                            SUCCESS
                          </span>
                          <span v-else class="bg-slate-100 text-slate-500 text-[9px] font-black px-2 py-0.5 rounded-full uppercase">
                            EXPIRED
                          </span>
                        </div>
                      </div>

                      <div class="flex-1 min-w-0 w-full sm:w-auto">
                        
                        <div v-if="alloc.status === 'active'" class="text-xs text-slate-400 font-black italic animate-pulse flex items-center gap-1">
                          <i class="fa-solid fa-spinner animate-spin"></i> Waiting for incoming SMS...
                        </div>
                        
                        <div v-else-if="alloc.status === 'completed'" @click="copyFullSms(alloc.message)" class="bg-emerald-50 hover:bg-emerald-100 border-2 border-emerald-200 p-2.5 rounded-2xl text-emerald-800 text-xs cursor-pointer active:scale-95 transition-all flex items-center justify-between gap-3 group animate-pulse">
                          <div class="min-w-0">
                            <span class="text-[9px] text-emerald-600 font-bold uppercase tracking-wider block">OTP CODE (CLICK TO COPY FULL SMS)</span>
                            <span class="text-lg md:text-xl font-black text-emerald-800 block tracking-widest mt-0.5">
                              {{ alloc.otp }}
                            </span>
                          </div>
                          <div class="bg-emerald-500 group-hover:bg-emerald-600 text-white h-8 w-8 rounded-xl flex items-center justify-center shrink-0 shadow-xs transition">
                            <i class="fa-regular fa-envelope-open text-xs"></i>
                          </div>
                        </div>
                        
                        <div v-else class="text-xs text-rose-500 font-bold">
                          Banned / Closed (18 mins over)
                        </div>

                      </div>

                      <div class="text-left sm:text-right shrink-0">
                        <p class="font-black text-slate-700 text-xs uppercase">{{ alloc.country }}</p>
                        <p class="text-[9px] text-slate-400 font-black uppercase mt-0.5">{{ alloc.operator }}</p>
                      </div>

                      <div class="shrink-0 w-full sm:w-auto flex justify-end">
                        <div class="bg-slate-50 border border-slate-200 text-slate-600 text-[11px] font-black py-1 px-3 rounded-xl min-w-[70px] text-center tracking-wider">
                          {{ alloc.status === 'active' && alloc.timeLeft > 0 ? formatTime(alloc.timeLeft) : '--:--' }}
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

              <!-- ==================== সেকশন ৪: পেমেন্ট ==================== -->
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

                <div class="bg-white p-5 rounded-3xl border border-slate-200 shadow-xs flex justify-between items-center">
                  <div>
                    <p class="text-[10px] font-bold text-slate-400 uppercase">মোট অর্জিত আয়</p>
                    <h2 class="text-xl font-black text-[#0088CC] mt-0.5">৳ {{ parseFloat(profile ? profile.balance : 0).toFixed(2) }}</h2>
                  </div>
                  <div class="bg-[#0088CC]/10 h-10 w-10 rounded-full flex items-center justify-center text-[#0088CC] text-md font-bold">৳</div>
                </div>
              </div>

              <!-- ==================== সেকশন ৫: প্রোফাইল ==================== -->
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
                      <p class="text-slate-500">এপিআই কি:</p>
                      
                      <div v-if="profile && profile.api_key" class="flex flex-col gap-2">
                        <span class="text-slate-800 font-mono text-[10px] bg-slate-50 px-3 py-2 rounded border break-all select-all">
                          {{ profile.api_key }}
                        </span>
                        <button @click="copyToClipboard(profile.api_key)" class="w-max bg-[#0088CC]/10 text-[#0088CC] font-bold px-3 py-1.5 rounded-xl text-[10px] hover:bg-[#0088CC]/20 transition">
                          কপি করুন <i class="fa-solid fa-copy ml-1"></i>
                        </button>
                      </div>
                      
                      <div v-else class="space-y-2">
                        <p class="text-amber-600 text-[10px] font-bold"><i class="fa-solid fa-triangle-exclamation"></i> কোনো এপিআই কি জেনারেট করা নেই। নিচের বাটনে ক্লিক করে স্থায়ী এপিআই কি তৈরি করুন।</p>
                        <button @click="handleGenerateApiKey" :disabled="apiGenLoading" class="bg-emerald-600 hover:bg-emerald-700 text-white font-black px-4 py-2.5 rounded-2xl text-[11px] tracking-wider transition active:scale-95 disabled:bg-slate-300">
                          {{ apiGenLoading ? 'তৈরি হচ্ছে...' : 'GENERATE API KEY' }}
                        </button>
                      </div>
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
                  if (profileData.user.wallet_address && !walletAddressInput.value) {
                    walletAddressInput.value = profileData.user.wallet_address;
                  }
                }
              } catch (e) {
                console.log("Profile Fetch Error:", e);
              }

              userLoaded.value = true; 

              // ২. ওটিপি ও অ্যাক্টিভ নম্বর লাইভ সিঙ্ক
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

            return {
              userLoaded, user, profile, authName, authEmail, authPassword, isRegistering, authLoading,
              currentTab, rid, nationalFormat, removePlus, activeNumber, activeCountry, activeOperator, otpResult, loadingNumber, liveLogs, successOtps,
              allocations, currentPage, itemsPerPage, paginatedAllocations, totalPages, prevPage, nextPage, searchQuery,
              showToast, toastMessage, copyToClipboard, copyFullSms, walletAddressInput, walletLoading, handleUpdateWallet,
              handleAuth, signOut, handleGetNumber, formatTime, formatTimestamp,
              apiGenLoading, handleGenerateApiKey
            };
          }
        }).mount('#app');
      </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype='text/html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 4000))
    app.run(host='0.0.0.0', port=port)