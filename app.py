import os
import secrets
import datetime
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# CORS পলিসি হ্যান্ডেল করার জন্য মেথড
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-MINO-API-KEY,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

# =========================================================================
# ইন-মেমোরি ডাটাবেজ (ফায়ারবেস সম্পূর্ণ রিমুভড)
# =========================================================================
users = {}            # { uid: {email, password, api_key, balance, otp_rate, id_code, createdAt} }
allocated_numbers = [] # [ {userId, number, rid, status, createdAt} ]
otp_logs = []          # [ {userId, number, service, otpCode, message, revenue, createdAt} ]
live_console = []      # [ {type, message, service, createdAt} ]

STEX_API_KEY = "MWF1Z0QG1DJ"
STEX_BASE_URL = "https://api.2oo9.cloud/MXS47FLFX8U/tness/gpubliic/api"

# নম্বর সিকিউরিটি মাস্কিং হেল্পার ফাংশন
def mask_number(number):
    if not number:
        return ''
    length = len(number)
    if length < 8:
        return number
    return f"{number[:6]}****{number[length-3:]}"

# টোকেন ব্যবহার করে রিকোয়েস্ট থেকে ইউজার খুঁজে বের করার ফাংশন
def get_current_user():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ')[1]
    return users.get(token)

# =========================================================================
# এপিআই ০: সিকিউর রেজিস্ট্রেশন (ইন-মেমোরি)
# =========================================================================
@app.route('/api/v1/auth/register', methods=['POST'])
def register():
    try:
        data = request.json or {}
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'status': 'error', 'message': 'Email and password are required'}), 400

        # চেক করা হচ্ছে মেইলটি আগে ব্যবহার করা হয়েছে কি না
        for u in users.values():
            if u['email'] == email:
                return jsonify({'status': 'error', 'message': 'Email already registered'}), 400

        uid = "usr_" + secrets.token_hex(8)
        unique_key = 'mino_live_' + secrets.token_hex(16)

        users[uid] = {
            'uid': uid,
            'email': email,
            'password': password,
            'api_key': unique_key,
            'balance': 0.00,
            'otp_rate': 0.50,
            'id_code': f"MINO-{secrets.randbelow(9000) + 1000}",
            'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        return jsonify({'status': 'success', 'token': uid, 'user': users[uid]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

# =========================================================================
# এপিআই ০.১: লগইন (ইন-মেমোরি)
# =========================================================================
@app.route('/api/v1/auth/login', methods=['POST'])
def login():
    try:
        data = request.json or {}
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'status': 'error', 'message': 'Email and password are required'}), 400

        for uid, u in users.items():
            if u['email'] == email and u['password'] == password:
                return jsonify({'status': 'success', 'token': uid, 'user': u})

        return jsonify({'status': 'error', 'message': 'Invalid email or password'}), 401
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# এপিআই ০.২: কারেন্ট ইউজার ডিটেইলস
# =========================================================================
@app.route('/api/v1/auth/me', methods=['GET'])
def get_me():
    u = get_current_user()
    if not u:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    return jsonify({'status': 'success', 'user': u})

# =========================================================================
# এপিআই ১: গেট নাম্বার
# =========================================================================
@app.route('/api/v1/getnum', methods=['GET'])
def getnum():
    try:
        rid = request.args.get('rid')
        api_key = request.headers.get('X-MINO-API-KEY') or request.args.get('api_key')

        if not api_key or not rid:
            return jsonify({'status': 'error', 'message': 'API Key or RID missing'}), 400

        # এপিআই কী দিয়ে ইউজার খোঁজা
        user = None
        for u in users.values():
            if u['api_key'] == api_key:
                user = u
                break

        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key'}), 403

        user_id = user['uid']

        stex_response = requests.post(
            f"{STEX_BASE_URL}/getnum",
            json={'rid': rid},
            headers={'mauthapi': STEX_API_KEY},
            timeout=10
        )
        
        if stex_response.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Gateway Temporarily Busy'}), 502

        stex_data = stex_response.json()
        if stex_data.get('status') != 'ok':
            return jsonify({'status': 'error', 'message': 'No number available on this range'}), 400

        number = stex_data['data']['full_number']

        allocated_numbers.append({
            'userId': user_id,
            'number': number,
            'rid': rid,
            'status': 'active',
            'createdAt': datetime.datetime.now(datetime.timezone.utc)
        })

        live_console.append({
            'type': 'allocation',
            'message': f"Number {mask_number(number)} requested on range {rid}",
            'service': stex_data['data'].get('operator', 'STEX Gateway'),
            'createdAt': datetime.datetime.now(datetime.timezone.utc)
        })

        return jsonify({
            'status': 'success',
            'number': number,
            'country': stex_data['data'].get('country'),
            'operator': stex_data['data'].get('operator')
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# এপিআই ২: ওটিপি চেক (জিরো-লেটেন্সি ইন্টিগ্রেশন)
# =========================================================================
@app.route('/api/v1/get-otp', methods=['GET'])
def get_otp():
    try:
        number = request.args.get('number')
        api_key = request.headers.get('X-MINO-API-KEY') or request.args.get('api_key')

        if not api_key or not number:
            return jsonify({'status': 'error', 'message': 'API Key and Number are required'}), 400

        user = None
        for u in users.values():
            if u['api_key'] == api_key:
                user = u
                break

        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key'}), 403

        user_id = user['uid']
        otp_rate = float(user.get('otp_rate', 0.50))

        # বরাদ্দকৃত নম্বর রেকর্ড খোঁজা হচ্ছে
        alloc = None
        for item in allocated_numbers:
            if item['number'] == number and item['userId'] == user_id:
                alloc = item
                break

        if not alloc:
            return jsonify({'status': 'error', 'message': 'Number record not found'}), 404

        created_at = alloc.get('createdAt')
        diff_seconds = 0
        is_expired = False
        if created_at:
            now = datetime.datetime.now(datetime.timezone.utc)
            diff = now - created_at
            diff_seconds = diff.total_seconds()
            is_expired = diff_seconds > (18 * 60)

        if is_expired or alloc.get('status') == 'expired':
            alloc['status'] = 'expired'
            return jsonify({'status': 'expired', 'message': 'Number expired (18 mins over)'})

        # অলরেডি ওটিপি এসে থাকলে তা চেক করা হচ্ছে
        existing_otp = None
        for log in otp_logs:
            if log['number'] == number and log['userId'] == user_id:
                existing_otp = log
                break

        if existing_otp:
            return jsonify({
                'status': 'success',
                'otp': existing_otp.get('otpCode'),
                'message': existing_otp.get('message'),
                'service': existing_otp.get('service')
            })

        stex_response = requests.get(f"{STEX_BASE_URL}/success-otp", headers={'mauthapi': STEX_API_KEY}, timeout=10)
        
        if stex_response.status_code == 200:
            stex_data = stex_response.json()
            if stex_data.get('status') == 'ok' and stex_data['data'].get('number') == number:
                otp_data = stex_data['data']
                message = otp_data.get('message', '').lower()
                service = None

                if 'facebook' in message or 'fb' in message:
                    service = 'facebook'
                elif 'instagram' in message or 'ig' in message:
                    service = 'instagram'

                if service:
                    # ব্যালেন্স আপডেট
                    user['balance'] = float(user.get('balance', 0.0)) + otp_rate

                    otp_logs.append({
                        'userId': user_id,
                        'number': number,
                        'service': service,
                        'otpCode': otp_data.get('otp'),
                        'message': otp_data.get('message'),
                        'revenue': otp_rate,
                        'stexTime': otp_data.get('time'),
                        'createdAt': datetime.datetime.now(datetime.timezone.utc)
                    })

                    alloc['status'] = 'completed'

                    live_console.append({
                        'type': 'otp_success',
                        'message': f"HIT! {service.upper()} OTP Received on {mask_number(number)}!",
                        'service': service,
                        'createdAt': datetime.datetime.now(datetime.timezone.utc)
                    })

                    return jsonify({
                        'status': 'success',
                        'otp': otp_data.get('otp'),
                        'message': otp_data.get('message'),
                        'service': service
                    })

        seconds_left = max(0, int(18 * 60 - diff_seconds))
        return jsonify({'status': 'pending', 'seconds_left': seconds_left})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# এপিআই ৩: ওটিপি তালিকা দেখা
# =========================================================================
@app.route('/api/v1/success-otp', methods=['GET'])
def success_otp():
    try:
        api_key = request.headers.get('X-MINO-API-KEY') or request.args.get('api_key')
        if not api_key:
            return jsonify({'status': 'error', 'message': 'API Key is required'}), 401

        user = None
        for u in users.values():
            if u['api_key'] == api_key:
                user = u
                break

        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid API Key'}), 403

        # ওটিপি রিভার্স সর্ট
        user_logs = [log for log in otp_logs if log['userId'] == user['uid']]
        user_logs.sort(key=lambda x: x['createdAt'], reverse=True)

        data = []
        for d in user_logs[:15]:
            created_at = d.get('createdAt')
            data.append({
                'number': d.get('number'),
                'service': d.get('service'),
                'otp_code': d.get('otpCode'),
                'message': d.get('message'),
                'revenue_earned': d.get('revenue'),
                'created_at': created_at.isoformat() if isinstance(created_at, datetime.datetime) else created_at
            })

        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# =========================================================================
# এপিআই ৪: গ্লোবাল কনসোল ডাটা রিড (পোলিংয়ের জন্য)
# =========================================================================
@app.route('/api/v1/live-console', methods=['GET'])
def get_live_console():
    # সর্বশেষ ১০ টি লগ পাঠানো হচ্ছে
    logs_desc = sorted(live_console, key=lambda x: x['createdAt'], reverse=True)[:10]
    data = []
    for log in logs_desc:
        created_at = log['createdAt']
        data.append({
            'type': log['type'],
            'message': log['message'],
            'service': log['service'],
            'createdAt': created_at.isoformat() if isinstance(created_at, datetime.datetime) else created_at
        })
    return jsonify({'status': 'success', 'data': data})

# =========================================================================
# ফ্রন্টএন্ড UI পরিবেশন (Serving the Frontend Page)
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
      <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
      <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
      <style>
        [v-cloak] { display: none; }
        body { background-color: #F3F7FA; }
      </style>
    </head>
    <body class="text-slate-700 font-sans">
      <div id="app" v-cloak>

        <!-- লগইন / সাইনআপ উইন্ডো -->
        <div v-if="!user" class="min-h-screen flex items-center justify-center p-4">
          <div class="bg-white p-8 rounded-3xl border border-slate-200 shadow-sm max-w-md w-full space-y-6">
            <div class="text-center space-y-2">
              <span class="px-3 py-1.5 bg-[#0088CC] rounded-2xl flex items-center justify-center text-white font-black text-lg mx-auto shadow-md">MINO</span>
              <h1 class="text-2xl font-black text-slate-900">MINO SMS PANEL</h1>
              <p class="text-xs font-semibold text-[#0088CC] uppercase tracking-widest">{{ isRegistering ? 'Register account' : 'Sign in to network' }}</p>
            </div>

            <form @submit.prevent="handleAuth" class="space-y-4">
              <div>
                <label class="text-xs font-bold text-slate-500">Email</label>
                <input type="email" required v-model="authEmail" placeholder="gopal@network.com" class="w-full mt-1.5 p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-[#0088CC] transition" />
              </div>
              <div>
                <label class="text-xs font-bold text-slate-500">Password</label>
                <input type="password" required v-model="authPassword" placeholder="••••••••" class="w-full mt-1.5 p-3 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:border-[#0088CC] transition" />
              </div>

              <button type="submit" :disabled="authLoading" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-3 rounded-xl text-sm shadow-md transition disabled:bg-slate-300">
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
          
          <!-- সাইডবার -->
          <aside class="w-full md:w-64 bg-white border-r border-slate-200 flex flex-col">
            <div class="p-6 border-b border-slate-100 flex items-center gap-3">
              <span class="px-2 py-1 bg-[#0088CC] rounded-lg flex items-center justify-center text-white font-black text-sm">MINO</span>
              <span class="text-lg font-black text-slate-950">MINO SMS</span>
              <span class="bg-[#0088CC]/10 text-[#0088CC] text-[10px] font-bold px-1.5 py-0.5 rounded-full ml-auto">V-3.0.2</span>
            </div>

            <!-- মেনু ক্যাটাগরি -->
            <nav class="flex-1 p-4 space-y-1">
              <button @click="currentTab = 'dashboard'" :class="currentTab === 'dashboard' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                <i class="fa-solid fa-house"></i> ড্যাশবোর্ড (Dashboard)
              </button>
              <button @click="currentTab = 'get-number'" :class="currentTab === 'get-number' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                <i class="fa-solid fa-mobile-screen"></i> নাম্বার নিন (Get Number)
              </button>
              <button @click="currentTab = 'console'" :class="currentTab === 'console' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                <i class="fa-solid fa-terminal"></i> কনসোল (Console)
              </button>
              <button @click="currentTab = 'payment'" :class="currentTab === 'payment' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                <i class="fa-solid fa-wallet"></i> পেমেন্ট (Payment)
              </button>
              <button @click="currentTab = 'profile'" :class="currentTab === 'profile' ? 'bg-[#0088CC]/10 text-[#0088CC]' : 'text-slate-600 hover:bg-slate-50'" class="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-semibold transition text-left">
                <i class="fa-solid fa-user"></i> প্রোফাইল (Profile)
              </button>
            </nav>

            <div class="p-4 border-t border-slate-100 flex items-center gap-3">
              <div class="h-9 w-9 bg-indigo-500 rounded-full flex items-center justify-center text-white font-bold text-sm">GV</div>
              <div class="flex-1">
                <p class="text-xs font-black text-slate-800">Gopal Var</p>
                <p class="text-[10px] text-slate-400">{{ user.email }}</p>
              </div>
              <button @click="signOut" class="text-slate-400 hover:text-rose-600"><i class="fa-solid fa-right-from-bracket"></i></button>
            </div>
          </aside>

          <!-- মেইন কন্টেন্ট এরিয়া -->
          <main class="flex-1 p-6 md:p-8 space-y-6 overflow-y-auto">
            
            <!-- টপ হেডার -->
            <header class="flex justify-between items-center border-b border-slate-200 pb-4">
              <div class="flex items-center gap-2">
                <span class="h-2.5 w-2.5 bg-[#0088CC] rounded-full"></span>
                <h2 class="text-lg font-black text-slate-900 capitalize">{{ currentTab.replace('-', ' ') }} Panel</h2>
              </div>
              <div class="flex items-center gap-4">
                <button class="relative h-9 w-9 bg-white border border-slate-200 rounded-full flex items-center justify-center text-slate-600 hover:bg-slate-50">
                  <i class="fa-solid fa-bell"></i>
                  <span class="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] font-bold h-4 w-4 rounded-full flex items-center justify-center">3</span>
                </button>
                <span class="bg-[#0088CC] text-white text-xs font-bold px-3 py-1.5 rounded-full shadow-sm">GV</span>
              </div>
            </header>

            <!-- ==================== সেকশন ১: ড্যাশবোর্ড ==================== -->
            <div v-if="currentTab === 'dashboard'" class="space-y-8">
              
              <!-- Wallet & OTP Report -->
              <div>
                <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">WALLET & OTP REPORT</h3>
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  
                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-emerald-50 h-12 w-12 rounded-full flex items-center justify-center text-emerald-600"><i class="fa-solid fa-wallet text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">ওয়ালেট ব্যালেন্স</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">৳ {{ parseFloat(profile ? profile.balance : 0).toFixed(2) }}</h4>
                    </div>
                  </div>

                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-amber-50 h-12 w-12 rounded-full flex items-center justify-center text-amber-600"><i class="fa-solid fa-tag text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">আপনার ওটিপি রেট</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">৳ {{ parseFloat(profile ? profile.otp_rate : 0.50).toFixed(2) }}</h4>
                    </div>
                  </div>

                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-blue-50 h-12 w-12 rounded-full flex items-center justify-center text-blue-600"><i class="fa-solid fa-box text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">আজকের মোট ওটিপি</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">{{ successOtps.length }}</h4>
                    </div>
                  </div>

                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-violet-50 h-12 w-12 rounded-full flex items-center justify-center text-violet-600"><i class="fa-solid fa-envelope text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">গতকালকের মোট ওটিপি</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">0</h4>
                    </div>
                  </div>

                </div>
              </div>

              <!-- Virtual Numbers Analytics -->
              <div>
                <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">VIRTUAL NUMBERS ANALYTICS</h3>
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  
                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-blue-50 h-12 w-12 rounded-full flex items-center justify-center text-blue-600"><i class="fa-solid fa-list-numeric text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">আজকের মোট নাম্বার</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">0</h4>
                    </div>
                  </div>

                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-emerald-50 h-12 w-12 rounded-full flex items-center justify-center text-emerald-600"><i class="fa-solid fa-circle-check text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">আজকের সফল নাম্বার</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">0</h4>
                    </div>
                  </div>

                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-amber-50 h-12 w-12 rounded-full flex items-center justify-center text-amber-600"><i class="fa-solid fa-tower-broadcast text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">গতকালকের মোট নাম্বার</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">0</h4>
                    </div>
                  </div>

                  <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                    <div class="bg-purple-50 h-12 w-12 rounded-full flex items-center justify-center text-purple-600"><i class="fa-solid fa-folder-closed text-lg"></i></div>
                    <div>
                      <p class="text-xs text-slate-400 font-semibold">গতকালকের সফল নাম্বার</p>
                      <h4 class="text-xl font-bold text-slate-900 mt-1">0</h4>
                    </div>
                  </div>

                </div>
              </div>

            </div>

            <!-- ==================== সেকশন ২: নাম্বার নিন ==================== -->
            <div v-if="currentTab === 'get-number'" class="space-y-6">
              
              <!-- 4 metrics -->
              <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div class="bg-white p-4 rounded-2xl border border-slate-200 flex items-center gap-3">
                  <div class="bg-slate-100 h-9 w-9 rounded-lg flex items-center justify-center text-slate-500"><i class="fa-solid fa-chart-bar text-sm"></i></div>
                  <div>
                    <p class="text-[10px] text-slate-400 font-bold uppercase">TODAY'S TOTAL</p>
                    <h5 class="text-sm font-black text-slate-900">0</h5>
                  </div>
                </div>
                <div class="bg-emerald-50 p-4 rounded-2xl border border-emerald-100 flex items-center gap-3">
                  <div class="bg-emerald-100/50 h-9 w-9 rounded-lg flex items-center justify-center text-emerald-600"><i class="fa-solid fa-circle-check text-sm"></i></div>
                  <div>
                    <p class="text-[10px] text-emerald-600 font-bold uppercase">OTP SUCCESS</p>
                    <h5 class="text-sm font-black text-emerald-700">0</h5>
                  </div>
                </div>
                <div class="bg-amber-50 p-4 rounded-2xl border border-amber-100 flex items-center gap-3">
                  <div class="bg-amber-100/50 h-9 w-9 rounded-lg flex items-center justify-center text-amber-600"><i class="fa-solid fa-clock-rotate-left text-sm"></i></div>
                  <div>
                    <p class="text-[10px] text-amber-600 font-bold uppercase">LIVE PENDING</p>
                    <h5 class="text-sm font-black text-amber-700">0</h5>
                  </div>
                </div>
                <div class="bg-rose-50 p-4 rounded-2xl border border-rose-100 flex items-center gap-3">
                  <div class="bg-rose-100/50 h-9 w-9 rounded-lg flex items-center justify-center text-rose-600"><i class="fa-solid fa-triangle-exclamation text-sm"></i></div>
                  <div>
                    <p class="text-[10px] text-rose-600 font-bold uppercase">FAILED/LOST</p>
                    <h5 class="text-sm font-black text-rose-700">0</h5>
                  </div>
                </div>
              </div>

              <!-- Range Box UI -->
              <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4">
                <div class="flex items-center gap-2 text-xs font-bold text-slate-400 uppercase tracking-widest">
                  <i class="fa-solid fa-mobile-button text-[#0088CC]"></i> Your Choice Range
                </div>
                <input type="text" v-model="rid" class="w-full p-4 bg-slate-50 border border-slate-200 rounded-2xl text-lg font-black outline-none tracking-wide text-[#0088CC] focus:border-[#0088CC]" />
                
                <div class="flex items-center gap-4 text-xs font-bold text-slate-400 py-1">
                  <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" class="rounded text-[#0088CC]" /> National Format</label>
                  <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" class="rounded text-[#0088CC]" /> Remove (+)</label>
                </div>

                <button @click="handleGetNumber" :disabled="loadingNumber" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-4 rounded-2xl shadow-md transition flex items-center justify-center gap-2 disabled:bg-slate-300">
                  <i v-if="loadingNumber" class="fa-solid fa-spinner animate-spin"></i>
                  <span class="tracking-widest"><i class="fa-solid fa-bolt mr-1"></i> GET NUMBER</span>
                </button>
              </div>

              <!-- Active/Logs Number Table -->
              <div class="bg-white rounded-3xl border border-slate-200 shadow-sm overflow-hidden">
                <div class="p-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
                  <h4 class="font-bold text-xs text-slate-400 uppercase tracking-widest">Active Phone Allocations</h4>
                  <button @click="handleCheckOtp" class="text-xs text-[#0088CC] font-bold hover:underline"><i class="fa-solid fa-arrows-rotate mr-1"></i> Refresh</button>
                </div>

                <div class="overflow-x-auto">
                  <table class="w-full text-left text-xs">
                    <thead class="bg-slate-50 uppercase text-slate-400 font-bold border-b border-slate-100">
                      <tr>
                        <th class="p-4">PHONE & STATUS</th>
                        <th class="p-4">OTP / SMS</th>
                        <th class="p-4">COUNTRY / OPERATOR</th>
                        <th class="p-4">TIMER / EXPIRY</th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                      <tr v-if="!activeNumber">
                        <td colspan="4" class="p-8 text-center text-slate-400 font-semibold">No active allocations found. Enter a range and click Get Number!</td>
                      </tr>
                      <tr v-else>
                        <td class="p-4">
                          <p class="font-bold text-slate-800 text-sm">{{ activeNumber }}</p>
                          <span class="bg-amber-100 text-amber-700 text-[9px] font-black px-2 py-0.5 rounded-full mt-1 inline-block uppercase">PENDING</span>
                        </td>
                        <td class="p-4">
                          <p v-if="!otpResult" class="text-slate-400 font-semibold animate-pulse">Waiting for incoming SMS...</p>
                          <div v-else class="bg-emerald-50 border border-emerald-100 p-2.5 rounded-xl text-emerald-800">
                            <strong>{{ otpResult.otp }}</strong> - {{ otpResult.message }}
                          </div>
                        </td>
                        <td class="p-4">
                          <p class="font-bold text-slate-700">IVORY COAST</p>
                          <p class="text-[10px] text-slate-400 uppercase">AIRCOMM SA</p>
                        </td>
                        <td class="p-4">
                          <div v-if="timeLeft > 0" class="bg-amber-50 text-amber-700 text-xs font-bold py-1 px-3 rounded-full inline-block">
                            {{ formatTime(timeLeft) }}
                          </div>
                          <div v-else class="bg-rose-50 text-rose-600 text-xs font-bold py-1 px-3 rounded-full inline-block">
                            EXPIRED / OFF
                          </div>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

            </div>

            <!-- ==================== সেকশন ৩: কনসোল (Global Radar) ==================== -->
            <div v-if="currentTab === 'console'" class="space-y-6">
              
              <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm flex justify-between items-center">
                <div>
                  <div class="flex items-center gap-2">
                    <i class="fa-solid fa-satellite-dish text-[#0088CC] text-xl animate-pulse"></i>
                    <h2 class="text-lg font-black text-slate-900">GLOBAL RADAR</h2>
                  </div>
                  <p class="text-xs text-slate-400 font-medium mt-1">Intercepting latest 100 secure network signals.</p>
                </div>
                <span class="bg-red-50 text-red-600 text-[10px] font-black px-3 py-1 rounded-full border border-red-100 uppercase flex items-center gap-1">
                  <span class="h-1.5 w-1.5 bg-red-600 rounded-full animate-ping"></span> Live Radar
                </span>
              </div>

              <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4">
                <span class="text-xs font-black text-slate-400 uppercase tracking-widest"><i class="fa-solid fa-chart-simple mr-1"></i> Network Traffic Intelligence</span>
                <div class="h-36 flex items-end gap-6 px-4 border-b border-slate-100">
                  <div class="w-full bg-[#0088CC] rounded-t-md h-32 flex items-center justify-center text-white text-[10px] font-bold">Facebook</div>
                  <div class="w-1/4 bg-rose-500 rounded-t-md h-4 flex items-center justify-center text-white text-[10px] font-bold">Instagram</div>
                  <div class="w-1/4 bg-amber-500 rounded-t-md h-2 flex items-center justify-center text-white text-[10px] font-bold">Network</div>
                </div>
              </div>

              <div class="bg-white p-4 rounded-2xl border border-slate-200 flex items-center gap-3">
                <i class="fa-solid fa-magnifying-glass text-slate-400"></i>
                <input type="text" placeholder="Search intercepted platform (e.g. facebook)" class="w-full text-sm outline-none font-semibold text-slate-700 bg-transparent" />
                <button class="bg-[#0088CC] hover:bg-[#0077B5] text-white p-2.5 rounded-xl"><i class="fa-solid fa-arrows-rotate"></i></button>
              </div>

              <div class="space-y-4">
                <div v-if="liveLogs.length === 0" class="p-12 text-slate-400 text-center font-semibold bg-white border rounded-3xl">Radar initializing... Listening for signals...</div>
                <div v-else v-for="log in liveLogs" :key="log.id" class="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex justify-between items-center animate-fade-in">
                  <div class="space-y-1">
                    <span class="bg-[#0088CC]/10 text-[#0088CC] text-[10px] font-black px-2 py-0.5 rounded-full mr-2">LIVE INTERCEPT</span>
                    <p class="font-mono font-black text-slate-800 text-sm mt-1">{{ log.message }}</p>
                    <p class="text-[10px] text-slate-400 capitalize">{{ log.service || 'Global Gateway' }}</p>
                  </div>
                  <button class="bg-slate-50 hover:bg-slate-100 text-slate-500 text-xs font-bold px-3 py-2 rounded-xl flex items-center gap-1 transition">
                    <i class="fa-solid fa-copy"></i> Copy
                  </button>
                </div>
              </div>

            </div>

            <!-- ==================== সেকশন ৪: পেমেন্ট ==================== -->
            <div v-if="currentTab === 'payment'" class="space-y-6">
              
              <div class="bg-white p-6 rounded-3xl border border-[#0088CC]/20 shadow-xs space-y-4">
                <h3 class="font-black text-sm text-slate-800 flex items-center gap-2"><i class="fa-solid fa-wallet text-[#0088CC]"></i> ওয়ালেট সেটআপ</h3>
                <div class="bg-indigo-50/50 border border-indigo-100 p-4 rounded-xl flex justify-between items-center">
                  <div>
                    <p class="text-[10px] text-slate-400 font-bold uppercase">Binance Pay ID / TRC20 (Active)</p>
                    <p class="font-mono font-black text-indigo-700 mt-1">1229559831</p>
                  </div>
                  <span class="bg-[#0088CC] text-white text-xs font-bold px-3 py-1.5 rounded-full shadow-sm"><i class="fa-brands fa-bitcoin"></i> TRC20</span>
                </div>
                <p class="text-xs text-amber-600 bg-amber-50 p-3 rounded-lg border border-amber-100 leading-relaxed"><i class="fa-solid fa-triangle-exclamation mr-1"></i> আপনার ওয়ালেট পরিবর্তন বা আপডেট করতে চাইলে আপনার এজেন্টের সাথে যোগাযোগ করুন।</p>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm flex justify-between items-center">
                  <div>
                    <p class="text-xs font-semibold text-slate-400 uppercase tracking-wider">বর্তমান ব্যালেন্স</p>
                    <h2 class="text-3xl font-black text-[#0088CC] mt-1">৳ {{ parseFloat(profile ? profile.balance : 0).toFixed(2) }}</h2>
                  </div>
                  <div class="bg-[#0088CC]/10 h-12 w-12 rounded-full flex items-center justify-center text-[#0088CC] text-lg font-bold">৳</div>
                </div>

                <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-3">
                  <h4 class="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1.5"><i class="fa-solid fa-lock text-rose-500"></i> উইথড্র রিকোয়েস্ট দিন</h4>
                  <p class="text-xs text-rose-600 bg-rose-50 p-3 rounded-lg border border-rose-100 font-bold"><i class="fa-solid fa-triangle-exclamation mr-1"></i> অ্যাডমিন কর্তৃক পেমেন্ট সিস্টেম সাময়িকভাবে বন্ধ রাখা হয়েছে। অনুগ্রহ করে অপেক্ষা করুন।</p>
                </div>

              </div>

              <div class="bg-white rounded-3xl border border-slate-200 shadow-sm overflow-hidden">
                <div class="p-4 border-b border-slate-200 bg-slate-50">
                  <h3 class="font-bold text-sm text-slate-800">উইথড্র ইতিহাস (Withdrawal Logs)</h3>
                </div>
                <div class="p-12 text-center text-slate-400 font-semibold text-xs">No withdrawal history found.</div>
              </div>

            </div>

            <!-- ==================== সেকশন ৫: প্রোফাইল ==================== -->
            <div v-if="currentTab === 'profile'" class="space-y-6">
              
              <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm flex items-center gap-6">
                <div class="h-20 w-20 bg-indigo-500 rounded-full flex items-center justify-center text-white font-bold text-sm">GV</div>
                <div class="flex-1">
                  <p class="text-xs font-black text-slate-800">Gopal Var</p>
                  <p class="text-[10px] text-slate-400">{{ user.email }}</p>
                </div>
              </div>

              <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4">
                <h3 class="font-bold text-sm text-slate-800 border-b border-slate-100 pb-2">ব্যক্তিগত তথ্য</h3>
                
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label class="text-xs font-bold text-slate-400 uppercase">সম্পূর্ণ নাম</label>
                    <input type="text" readonly value="Gopal Var" class="w-full mt-1.5 p-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none" />
                  </div>
                  <div>
                    <label class="text-xs font-bold text-slate-400 uppercase">মোবাইল নম্বর</label>
                    <input type="text" readonly value="01722259318" class="w-full mt-1.5 p-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold outline-none" />
                  </div>
                </div>

                <div class="pt-4 flex flex-wrap gap-4">
                  <button class="bg-[#0088CC]/10 hover:bg-[#0088CC]/20 text-[#0088CC] text-xs font-bold px-4 py-2.5 rounded-xl transition"><i class="fa-solid fa-link mr-1"></i> Link Google Account</button>
                  <button class="bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs font-bold px-4 py-2.5 rounded-xl transition"><i class="fa-solid fa-paper-plane mr-1"></i> Contact Agent</button>
                </div>
              </div>

              <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4">
                <h3 class="font-bold text-sm text-slate-800">অফিশিয়াল চ্যানেল</h3>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <a href="#" class="bg-sky-50 hover:bg-sky-100 p-4 rounded-2xl border border-sky-100 flex items-center justify-between text-sky-700 transition">
                    <span class="font-bold text-xs"><i class="fa-brands fa-telegram mr-1.5 text-lg"></i> Earning Center (মাদার কোম্পানি)</span>
                    <i class="fa-solid fa-circle-arrow-right"></i>
                  </a>
                  <a href="#" class="bg-sky-50 hover:bg-sky-100 p-4 rounded-2xl border border-sky-100 flex items-center justify-between text-sky-700 transition">
                    <span class="font-bold text-xs"><i class="fa-brands fa-telegram mr-1.5 text-lg"></i> MK Official (সাব ব্র্যান্ড)</span>
                    <i class="fa-solid fa-circle-arrow-right"></i>
                  </a>
                </div>
              </div>

            </div>

          </main>
        </div>
      </div>

      <script>
        const { createApp, ref, onMounted, watch } = Vue;

        createApp({
          setup() {
            const user = ref(null);
            const profile = ref(null);
            const authEmail = ref('');
            const authPassword = ref('');
            const isRegistering = ref(false);
            const authLoading = ref(false);

            const currentTab = ref('dashboard');

            const rid = ref('225071XXXXXXX');
            const activeNumber = ref(null);
            const otpResult = ref(null);
            const loadingNumber = ref(false);
            const liveLogs = ref([]);
            const successOtps = ref([]);
            const timeLeft = ref(1080);
            const windowOrigin = ref(''); 
            let timer = null;
            let pollingTimer = null;

            // ডাটা পোলিং শুরু করার মেথড (ফায়ারবেস স্ন্যাপশটের বিকল্প)
            const startPolling = () => {
              stopPolling();
              fetchData();
              pollingTimer = setInterval(fetchData, 4000); // প্রতি ৪ সেকেন্ড পর ডাটা আপডেট হবে
            };

            const stopPolling = () => {
              if (pollingTimer) {
                clearInterval(pollingTimer);
                pollingTimer = null;
              }
            };

            const fetchData = async () => {
              const token = localStorage.getItem('mino_session_token');
              if (!token) return;

              // ১. ইউজার প্রোফাইল ডাটা ফেচ
              try {
                const profileRes = await fetch('/api/v1/auth/me', {
                  headers: { 'Authorization': `Bearer ${token}` }
                });
                const profileData = await profileRes.json();
                if (profileData.status === 'success') {
                  user.value = profileData.user;
                  profile.value = profileData.user;
                } else {
                  signOut();
                  return;
                }
              } catch (e) {}

              // ২. গ্লোবাল লাইভ কনসোল ডাটা ফেচ
              try {
                const consoleRes = await fetch('/api/v1/live-console');
                const consoleData = await consoleRes.json();
                if (consoleData.status === 'success') {
                  liveLogs.value = consoleData.data;
                }
              } catch (e) {}

              // ৩. সাকসেস ওটিপি ডাটা ফেচ
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

            onMounted(() => {
              windowOrigin.value = window.location.origin; 
              const token = localStorage.getItem('mino_session_token');
              if (token) {
                startPolling();
              }
            });

            watch(activeNumber, (newVal) => {
              if (newVal) {
                timeLeft.value = 1080;
                clearInterval(timer);
                timer = setInterval(() => {
                  if (timeLeft.value > 0) {
                    timeLeft.value--;
                  } else {
                    clearInterval(timer);
                  }
                }, 1000);
              }
            });

            const handleAuth = async () => {
              if (!authEmail.value || !authPassword.value) return;
              authLoading.value = true;
              try {
                const url = isRegistering.value ? '/api/v1/auth/register' : '/api/v1/auth/login';
                const res = await fetch(url, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ email: authEmail.value, password: authPassword.value })
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
              stopPolling();
            };

            const handleGetNumber = async () => {
              if (!profile.value) return;
              loadingNumber.value = true;
              otpResult.value = null;
              try {
                const res = await fetch('/api/v1/getnum?rid=' + rid.value + '&api_key=' + profile.value.api_key);
                const data = await res.json();
                if (data.status === 'success') {
                  activeNumber.value = data.number;
                } else {
                  alert(data.message);
                }
              } catch (err) {
                alert('Failed to get number');
              }
              loadingNumber.value = false;
            };

            const handleCheckOtp = async () => {
              if (!activeNumber.value || !profile.value) return;
              try {
                const res = await fetch('/api/v1/get-otp?number=' + activeNumber.value + '&api_key=' + profile.value.api_key);
                const data = await res.json();
                if (data.status === 'success') {
                  otpResult.value = data;
                } else if (data.status === 'expired') {
                  alert('Number expired.');
                }
              } catch (err) {
                alert('Failed to check OTP');
              }
            };

            const formatTime = (seconds) => {
              const mins = Math.floor(seconds / 60);
              const secs = seconds % 60;
              return mins + ':' + (secs < 10 ? '0' : '') + secs;
            };

            return {
              user, profile, authEmail, authPassword, isRegistering, authLoading,
              currentTab, rid, activeNumber, otpResult, loadingNumber, liveLogs, successOtps, timeLeft,
              windowOrigin, handleAuth, signOut, handleGetNumber, handleCheckOtp, formatTime, window
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