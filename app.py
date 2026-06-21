import os
import re
import json
import secrets
import datetime
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# CORS এবং এন্টি-ক্যাশিং পলিসি (ব্রাউজার বা Pydroid-এ ক্যাশিং সমস্যা এড়াতে)
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

# =========================================================================
# ভার্সেল ও লোকাল প্ল্যাটফর্মের জন্য ক্র্যাশ-ফ্রি হাইব্রিড ডাটাবেজ (db.json)
# =========================================================================
DB_FILE = "db.json"
MEMORY_DB = None

def load_db():
    global MEMORY_DB
    if MEMORY_DB is not None:
        return MEMORY_DB
    
    # পদ্ধতি ১: লোকাল ফাইল রিড
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                MEMORY_DB = json.load(f)
                return MEMORY_DB
        except Exception:
            pass
            
    # পদ্ধতি ২: ভার্সেল রাইট ডিরেক্টরি রিড
    tmp_path = "/tmp/db.json"
    if os.path.exists(tmp_path):
        try:
            with open(tmp_path, 'r', encoding='utf-8') as f:
                MEMORY_DB = json.load(f)
                return MEMORY_DB
        except Exception:
            pass

    # পদ্ধতি ৩: ইন-মেমোরি ইনিশিয়েলাইজ
    MEMORY_DB = {
        "users": {},
        "allocated_numbers": [],
        "otp_logs": [],
        "live_console": []
    }
    return MEMORY_DB

def save_db(db_data):
    global MEMORY_DB
    MEMORY_DB = db_data
    
    # লোকাল ডিরেক্টরিতে সেভ করার ট্রাই
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db_data, f, indent=4, ensure_ascii=False)
            return
    except Exception:
        pass
        
    # ভার্সেল টেম্পোরারি ফোল্ডারে সেভ করার ট্রাই (ক্র্যাশ প্রতিরোধ করবে)
    try:
        tmp_path = "/tmp/db.json"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(db_data, f, indent=4, ensure_ascii=False)
            return
    except Exception:
        pass

STEX_API_KEY = "MWF1Z0QG1DJ"
STEX_BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api"

def mask_number(number):
    if not number:
        return ''
    length = len(number)
    if length < 8:
        return number
    return f"{number[:6]}****{number[length-3:]}"

# অথেনটিকেশন এবং এপিআই কি ইন্টিগ্রেটেড নিরাপদ পার্সার
def get_current_user(db):
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        user = db["users"].get(token)
        if user:
            return user

    # অল্টারনে티브 চেক: হেডার বা কুয়েরি কি
    api_key = request.headers.get('X-MINO-API-KEY') or request.args.get('api_key')
    if api_key:
        for u in db["users"].values():
            if u['api_key'] == api_key:
                return u
    return None

# =========================================================================
# এপিআইসমূহ
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
        unique_key = 'mino_live_' + secrets.token_hex(16)

        db["users"][uid] = {
            'uid': uid,
            'name': name,
            'email': email,
            'password': password,
            'api_key': unique_key,
            'balance': 0.00,
            'otp_rate': 0.40,  # ওটিপি রেট ৪০ পয়সা সেট করা হলো
            'wallet_address': '', # নতুন ফাকা ওয়ালেট এড্রেস ফিল্ড
            'id_code': f"MINO-{secrets.randbelow(9000) + 1000}",
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        
        save_db(db)
        return jsonify({'status': 'success', 'token': uid, 'user': db["users"][uid]})
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

# ওয়ালেট এড্রেস সেটআপ করার এপিআই
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
        db["users"][user_id]['wallet_address'] = wallet_address
        save_db(db)
        
        return jsonify({'status': 'success', 'message': 'Wallet updated successfully', 'wallet_address': wallet_address})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/getnum', methods=['GET'])
def getnum():
    try:
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

        # পদ্ধতি ১: GET Request
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

        # পদ্ধতি ২: POST JSON
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

        db["allocated_numbers"].append({
            'userId': user_id,
            'number': number,
            'rid': rid,
            'status': 'active',
            'country': country,
            'operator': operator,
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

        db["live_console"].append({
            'type': 'allocation',
            'message': f"Number {mask_number(number)} requested on range {rid}",
            'service': operator,
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
        
        save_db(db)

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
                                    user['balance'] = float(user.get('balance', 0.0)) + otp_rate
                                    db["otp_logs"].append({
                                        'userId': user_id,
                                        'number': alloc['number'],
                                        'service': service,
                                        'otpCode': otp_code,
                                        'message': message,
                                        'revenue': otp_rate,
                                        'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
                                    })

                                alloc['status'] = 'completed'
                                alloc['otp'] = otp_code
                                alloc['message'] = message

                                db["live_console"].append({
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

        save_db(db)
        user_allocs.sort(key=lambda x: x.get('createdAt', ''), reverse=True)

        return jsonify({'status': 'success', 'allocations': user_allocs})
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
                    data.append({
                        'range': hit.get('range', 'N/A'),
                        'service': hit.get('sid', 'Global'),
                        'message': hit.get('message', ''),
                        'time': hit.get('time', 0)
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
      <!-- Tailwind CSS Play CDN (Arbitrary v3+ values সাপোর্ট করার জন্য) -->
      <script src="https://cdn.tailwindcss.com"></script>
      <!-- Vue 3 Global Production CDN (সঠিক .min.js ফাইল লোড করা হলো) -->
      <script src="https://cdnjs.cloudflare.com/ajax/libs/vue/3.3.4/vue.global.prod.min.js"></script>
      <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
      <style>
        [v-cloak] { display: none; }
        body { background-color: #F8FAFC; }
      </style>
    </head>
    <body class="text-slate-700 font-sans select-none pb-16 md:pb-0">
      
      <div id="app">

        <!-- স্মার্ট লোডিং স্ক্রিন প্লেসহোল্ডার (সাদা পেজ হওয়ার সমাধান) -->
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
              
              <!-- টপ হেডার -->
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
                        <!-- ওটিপি রেট ডাইনামিকালি ৪০ পয়সা দেখাবে -->
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

                <!-- ওটিপি লগ লিস্ট -->
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
                
                <!-- Range Box UI -->
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

                <!-- সক্রিয় নম্বরের তালিকা -->
                <div class="space-y-4">
                  
                  <!-- লাইভ সার্চ বার ও পেজিনেশন -->
                  <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 px-2">
                    <input type="text" v-model="searchQuery" placeholder="নম্বর বা দেশ দিয়ে খুঁজুন..." class="w-full sm:w-64 p-3 bg-white border border-slate-200 rounded-2xl text-xs font-semibold outline-none focus:border-[#0088CC]" />
                    <div class="flex gap-2 text-[10px] font-bold text-slate-400 items-center">
                      <button @click="prevPage" :disabled="currentPage === 1" class="bg-white border rounded-xl px-3 py-1.5 disabled:opacity-50 shadow-xs">Prev</button>
                      <span>Page {{ currentPage }} of {{ totalPages }}</span>
                      <button @click="nextPage" :disabled="currentPage === totalPages" class="bg-white border rounded-xl px-3 py-1.5 disabled:opacity-50 shadow-xs">Next</button>
                    </div>
                  </div>

                  <!-- নম্বর আইটেমগুলির তালিকা (Screenshot 5 লেআউট) -->
                  <div v-if="paginatedAllocations.length === 0" class="bg-white p-12 text-center text-slate-400 border rounded-3xl font-semibold text-xs">
                    কোনো নম্বর তালিকা পাওয়া যায়নি।
                  </div>

                  <div v-else class="space-y-3">
                    <div v-for="alloc in paginatedAllocations" :key="alloc.createdAt" class="bg-white p-4 rounded-3xl border border-slate-200 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 transition hover:shadow-xs hover:border-slate-300">
                      
                      <!-- Left: Number & Status Badges -->
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

                      <!-- Middle Left: Dynamic OTP Box -->
                      <div class="flex-1 min-w-0 w-full sm:w-auto">
                        
                        <!-- অপেক্ষমান স্ট্যাটাস -->
                        <div v-if="alloc.status === 'active'" class="text-xs text-slate-400 font-black italic animate-pulse flex items-center gap-1">
                          <i class="fa-solid fa-spinner animate-spin"></i> Waiting for incoming SMS...
                        </div>
                        
                        <!-- ওটিপি সফল বক্স -->
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
                        
                        <!-- এক্সপায়ারড নম্বর -->
                        <div v-else class="text-xs text-rose-500 font-bold">
                          Banned / Closed (18 mins over)
                        </div>

                      </div>

                      <!-- Middle Right: Country/Operator -->
                      <div class="text-left sm:text-right shrink-0">
                        <p class="font-black text-slate-700 text-xs uppercase">{{ alloc.country }}</p>
                        <p class="text-[9px] text-slate-400 font-black uppercase mt-0.5">{{ alloc.operator }}</p>
                      </div>

                      <!-- Right Side: Expiry / Expiration Countdown -->
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
                        Range: {{ log.range }} (Click to Copy)
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

              <!-- ==================== সেকশন ৪: পেমেন্ট (নিরাপদ ওয়ালেট এডিটর সংযুক্ত) ==================== -->
              <div v-if="currentTab === 'payment'" class="space-y-6">
                
                <!-- ডাইনামিক ওয়ালেট কার্ড -->
                <div class="bg-white p-5 rounded-3xl border border-[#0088CC]/20 shadow-xs space-y-4">
                  <h3 class="font-black text-xs text-slate-800 flex items-center gap-2"><i class="fa-solid fa-wallet text-[#0088CC]"></i> ওয়ালেট এড্রেস সেট করুন (Binance / TRC20)</h3>
                  
                  <div class="bg-indigo-50/50 border border-indigo-100 p-4 rounded-xl flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                    <div>
                      <p class="text-[10px] text-slate-400 font-bold uppercase">BINANCE PAY ID / TRC20 ADDRESS</p>
                      <p class="font-mono font-black text-indigo-700 mt-1 select-all break-all">{{ user?.wallet_address || 'ওয়ালেট সেট করা নেই' }}</p>
                    </div>
                    <span class="bg-[#0088CC] text-white text-[10px] font-bold px-2.5 py-1 rounded-full shadow-sm"><i class="fa-brands fa-bitcoin"></i> TRC20</span>
                  </div>

                  <!-- ওয়ালেট আপডেট ফর্ম -->
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
                  <div class="space-y-2 font-semibold">
                    <p class="text-slate-500">ইউজার আইডি: <span class="text-slate-800 font-bold ml-1">{{ profile ? profile.uid : 'N/A' }}</span></p>
                    <p class="text-slate-500">এপিআই কি: <span class="text-slate-800 font-mono text-[10px] bg-slate-50 px-1.5 py-0.5 rounded break-all select-all ml-1">{{ profile ? profile.api_key : 'N/A' }}</span></p>
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
            const userLoaded = ref(false); // সাদা স্ক্রিন প্রতিরোধক লোডিং স্টেট
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
            
            // ওয়ালেট আপডেট ভেরিয়েবল
            const walletAddressInput = ref('');
            const walletLoading = ref(false);

            // সার্চ এবং ফিল্টারিং
            const searchQuery = ref('');

            // নম্বর লিস্ট এবং পেজিনেশন কনফিগারেশন (২০০ টি প্রতি পেজে)
            const allocations = ref([]);
            const currentPage = ref(1);
            const itemsPerPage = 200;

            // কপি ক্লিপবোর্ড টোস্ট
            const showToast = ref(false);
            const toastMessage = ref('');
            
            // পোলিং টাইমার ডিক্লেয়ার করা হলো (যাতে এরর না আসে)
            let pollingTimer = null; 

            // নোটিফিকেশন সাউন্ড প্লেয়ার (Beep Sound)
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

            // ডাইনামিক ফিল্টারকৃত নম্বর তালিকা
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

            // পেজিনেশন লজিক
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

            // ১৮ মিনিট চেক
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
              pollingTimer = setInterval(fetchData, 500); // ৫০০ মিলি-সেকেন্ড (১০ গুণ বেশি স্পিড)
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
                const profileData = await profileRes.json();
                if (profileData.status === 'success') {
                  user.value = profileData.user;
                  profile.value = profileData.user;
                  if (profileData.user.wallet_address && !walletAddressInput.value) {
                    walletAddressInput.value = profileData.user.wallet_address;
                  }
                } else {
                  signOut();
                  userLoaded.value = true;
                  return;
                }
              } catch (e) {}

              userLoaded.value = true; // লোডিং সমাপ্ত

              // ২. ওটিপি ও অ্যাক্টিভ নম্বর লাইভ সিঙ্ক
              if (profile.value) {
                try {
                  const allocRes = await fetch('/api/v1/user-allocations', {
                    headers: { 
                      'Authorization': `Bearer ${token}`,
                      'X-MINO-API-KEY': profile.value.api_key 
                    }
                  });
                  const allocData = await allocRes.json();
                  if (allocData.status === 'success') {
                    const prevCompletedCount = allocations.value.filter(a => a.status === 'completed').length;
                    
                    allocations.value = allocData.allocations;
                    updateTimers();

                    // সাউন্ড সংকেত
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
                  const otpRes = await fetch('/api/v1/success-otp?api_key=' + profile.value.api_key);
                  const otpData = await otpRes.json();
                  if (otpData.status === 'success') {
                    successOtps.value = otpData.data;
                  }
                } catch (e) {}
              }
            };

            // ওয়ালেট সেভ করার রিকোয়েস্ট হ্যান্ডেলার
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
                  fetchData(); // ১ ন্যানো-সেকেন্ড গতি রিফ্রেশ
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
              handleAuth, signOut, handleGetNumber, formatTime, formatTimestamp
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