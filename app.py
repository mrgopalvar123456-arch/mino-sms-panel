import os
import secrets
import datetime
import requests
from flask import Flask, request, jsonify, Response
import firebase_admin
from firebase_admin import credentials, firestore, auth

app = Flask(__name__)

# CORS পলিসি হ্যান্ডেল করার জন্য মেথড
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-MINO-API-KEY')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

# =========================================================================
# ফায়ারবেস ক্লায়েন্ট কনফিগারেশন (এখানে আপনার ফায়ারবেস ওয়েব অ্যাপের মানগুলো বসিয়ে দিন)
# =========================================================================
FIREBASE_CLIENT_CONFIG = {
    "apiKey": "এখানে_আপনার_Firebase_Web_API_Key_দিন",           # উদাহরণ: "AIzaSy..."
    "authDomain": "all-panel-support.firebaseapp.com",
    "projectId": "all-panel-support",
    "storageBucket": "all-panel-support.appspot.com",
    "messagingSenderId": "এখানে_আপনার_Messaging_Sender_ID_দিন", # উদাহরণ: "112981..."
    "appId": "এখানে_আপনার_Firebase_App_ID_দিন"                 # উদাহরণ: "1:112981..."
}

# ফায়ারবেস অ্যাডমিন ক্রেডেনশিয়াল জেসন
# (নিরাপত্তার সুবিধার্থে এগুলো এনভায়রনমেন্ট ভেরিয়েবল থেকে নেওয়ার চেষ্টা করবে, না পেলে হার্ডকোড করা মান ব্যবহার করবে)
firebase_creds = {
  "type": "service_account",
  "project_id": "all-panel-support",
  "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID", "f482e69eaee23c8be49b2394631ac36dd9201617"),
  "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDLp7LfbvuJaHBJ\nfqr54VUXwa35OYJq+7MnrjexU2+Cye3figOn/GgSGEKbSruDP2BD/isarRdNSShy\nB6eKphcn5/iQIfdWJx9oDdbK+VQrF7HfmvN3JVdoKLIOUCLlcLGGO2RuFuLFMhhh\ns+Iu8kX7TBFafVwP796+qrTNc4r4LqbbjB3lgfiMvWd5jUhbuWGJ8N8wd1mM/S9q\ndzTSx/w6yPAsKwRWySUHCI0o1S6E1RiFPLJDeLpp5wrzqn5IfzbqjAs9eh4HNAP5\nov4F5fhhXVp5b0xmNXcn7CfnIkX86VRC1mri4MO2LKV6Ld+A7rC1LG/fSDv1dDNk\nXZ7//821AgMBAAECggEAALQeMwA/aA4KEJrv13KpmFjVM3P5KR+gUr4Fl7woebdz\nC1oUS/zcKtnWGxK9m0UOswAaYS/MEY/ejvxLSM2XmA3zXCNzPGM2DCY7bH1C3EOV\n8VDn+pdQr2halcroP/TXzCqsMhGBVuSRfymVBGFWZWPxzbylTYcgNMuYBHtbys00\nNouHuM3+Ok1A4xa0XBaNMW3QKXFoPpoxCYEvZf6ZQoJwj3SyNBbXyVuNDSAExy6a\nFpfUZaWWdkzueeu4W/RelWbLiicGo0NQQJpVT4WtYj9Y5aTDxuD+GNBuANLK6pUO\n5ZDCiiIEXxyWodOiB40n1DECL4o3txppd7ZERAodWQKBgQDvKeq07AFAEfJ56JxU\nOXlPK4GhKR7kzlYDwDFl3ges5qCsg8PaamlfSCe+ezDmLNFrcwzhW/D32BXU67WG\n3KSkWGt3xS+TKxCCzHDnsOiIRzHuWM3vWkcSxcPiiEOD+zUzJP6OGAvJQpSgUpAQ\n3llXXG4+v+m3xSN/ZOez+6Zt2QKBgQDZ/d0IfXPertMBh/sX++iBMgyVdZnSfAQy\nssiylKYEZPxfSeQ0P2zSPSFbn4YNgtUbj5ghZW1xehly4HHGsxwDbKuGbrNdlvDj\n682mj2vIkTFiJnpB17Xi8/twhUK9D2UByhdv/k6dBtAu5YzSSi7IaxyNZ6b3h7QG\n3e99L3MJPQKBgQCXF3kiwXJswqnYIH8aqpCb1pV3dh4BWOV4SyQqAeIBdlYNhtTl\nmJJnUpNhQDx9PdUzt6RsfwQ137qzIBI3WA9fkEiciuNqaytsJrIxfU76QVgnBs1b\nKEJ8dpow8/sLV1mdrQJwTHqttDVnL6G6Nm5kxY0UcXO62H17jwjeaN4UyQKBgHAV\nkK3J22b3GvVhlqCZXM35DvFWO1Y3f+0Vcg4oUkhWKFFSa+zVY72hwuIaXtHZoHuA\nVKdvQFulfSpM7xNMiq3UFUmU59LKRmfama33dmL1DKA7yobKQ/JCotkTG+Kb5MKL\nx4tFBeTFWQuT6dlCXVWdhVvLnNUPSGhzeq0yVYK9AoGALaS7t6q/m39+sCigyDvZ\nW9L36TO/xtt02XrO3MwOQordHf3ovstohZRcAepf3kChYqJtoS+jTjXmdPWt38tl\n5gLDnsBJjl/vcW+2xhtPLFmIzoMtT/yTja6oI85MlsWXNX58F6Mk97OXM/i5HK8N\n3QfQiRb/u6F6f+gzT+v6JBU=\n-----END PRIVATE KEY-----\n"),
  "client_email": os.getenv("FIREBASE_CLIENT_EMAIL", "firebase-adminsdk-fbsvc@all-panel-support.iam.gserviceaccount.com"),
  "client_id": "112981434071027857034",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40all-panel-support.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()

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

# =========================================================================
# এপিআই ০: সিকিউর রেজিস্ট্রেশন (সার্ভার-সাইড)
# =========================================================================
@app.route('/api/v1/auth/register', methods=['POST'])
def register():
    try:
        data = request.json or {}
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({'status': 'error', 'message': 'Email and password are required'}), 400

        user_record = auth.create_user(email=email, password=password)
        unique_key = 'mino_live_' + secrets.token_hex(16)

        # প্রোফাইল তৈরি (ব্যালেন্স ডিফল্ট ০.০০, ওটিপি রেট ০.৫০)
        db.collection('profiles').document(user_record.uid).set({
            'email': email,
            'api_key': unique_key,
            'balance': 0.00,
            'otp_rate': 0.50,
            'id_code': f"MINO-{secrets.randbelow(9000) + 1000}",
            'createdAt': firestore.SERVER_TIMESTAMP
        })

        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

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

        users_ref = db.collection('profiles').where('api_key', '==', api_key).limit(1).stream()
        user_doc = next(users_ref, None)
        if not user_doc:
            return jsonify({'status': 'error', 'message': 'Invalid API Key'}), 403

        user_id = user_doc.id

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

        db.collection('allocated_numbers').add({
            'userId': user_id,
            'number': number,
            'rid': rid,
            'status': 'active',
            'createdAt': firestore.SERVER_TIMESTAMP
        })

        db.collection('live_console').add({
            'type': 'allocation',
            'message': f"Number {mask_number(number)} requested on range {rid}",
            'service': stex_data['data'].get('operator', 'STEX Gateway'),
            'createdAt': firestore.SERVER_TIMESTAMP
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

        users_ref = db.collection('profiles').where('api_key', '==', api_key).limit(1).stream()
        user_doc = next(users_ref, None)
        if not user_doc:
            return jsonify({'status': 'error', 'message': 'Invalid API Key'}), 403

        user_id = user_doc.id
        user_data = user_doc.to_dict()
        otp_rate = float(user_data.get('otp_rate', 0.50))

        num_ref = db.collection('allocated_numbers').where('number', '==', number).where('userId', '==', user_id).limit(1).stream()
        num_doc = next(num_ref, None)
        if not num_doc:
            return jsonify({'status': 'error', 'message': 'Number record not found'}), 404

        num_data = num_doc.to_dict()

        created_at = num_data.get('createdAt')
        diff_seconds = 0
        is_expired = False
        if created_at:
            now = datetime.datetime.now(datetime.timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=datetime.timezone.utc)
            diff = now - created_at
            diff_seconds = diff.total_seconds()
            is_expired = diff_seconds > (18 * 60)

        if is_expired or num_data.get('status') == 'expired':
            db.collection('allocated_numbers').document(num_doc.id).update({'status': 'expired'})
            return jsonify({'status': 'expired', 'message': 'Number expired (18 mins over)'})

        otp_ref = db.collection('otp_logs').where('number', '==', number).where('userId', '==', user_id).limit(1).stream()
        otp_doc = next(otp_ref, None)
        if otp_doc:
            existing_otp = otp_doc.to_dict()
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
                    # ব্যালেন্স ট্রানজেকশন আপডেট
                    user_ref = db.collection('profiles').document(user_id)
                    
                    @firestore.transactional
                    def update_balance_transaction(transaction, ref_obj):
                        snapshot = ref_obj.get(transaction=transaction)
                        current_balance = float(snapshot.get('balance') or 0.0)
                        transaction.update(ref_obj, {'balance': current_balance + otp_rate})

                    transaction = db.transaction()
                    update_balance_transaction(transaction, user_ref)

                    db.collection('otp_logs').add({
                        'userId': user_id,
                        'number': number,
                        'service': service,
                        'otpCode': otp_data.get('otp'),
                        'message': otp_data.get('message'),
                        'revenue': otp_rate,
                        'stexTime': otp_data.get('time'),
                        'createdAt': firestore.SERVER_TIMESTAMP
                    })

                    db.collection('allocated_numbers').document(num_doc.id).update({'status': 'completed'})

                    db.collection('live_console').add({
                        'type': 'otp_success',
                        'message': f"HIT! {service.upper()} OTP Received on {mask_number(number)}!",
                        'service': service,
                        'createdAt': firestore.SERVER_TIMESTAMP
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

        users_ref = db.collection('profiles').where('api_key', '==', api_key).limit(1).stream()
        user_doc = next(users_ref, None)
        if not user_doc:
            return jsonify({'status': 'error', 'message': 'Invalid API Key'}), 403

        otp_ref = db.collection('otp_logs')\
            .where('userId', '==', user_doc.id)\
            .order_by('createdAt', direction=firestore.Query.DESCENDING)\
            .limit(15).stream()

        data = []
        for doc in otp_ref:
            d = doc.to_dict()
            created_at = d.get('createdAt')
            data.append({
                'number': d.get('number'),
                'service': d.get('service'),
                'otp_code': d.get('otpCode'),
                'message': d.get('message'),
                'revenue_earned': d.get('revenue'),
                'created_at': created_at.isoformat() if created_at else None
            })

        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
      <script src="https://www.gstatic.com/firebasejs/9.23.0/firebase-app-compat.js"></script>
      <script src="https://www.gstatic.com/firebasejs/9.23.0/firebase-auth-compat.js"></script>
      <script src="https://www.gstatic.com/firebasejs/9.23.0/firebase-firestore-compat.js"></script>
      <style>
        [v-cloak] { display: none; }
        body { background-color: #F3F7FA; }
      </style>
    </head>
    <body class="text-slate-700 font-sans">
      <div id="app" v-cloak>
        
        <!-- এনভায়রনমেন্ট ভেরিয়েবল বা ফায়ারবেস কনফিগারেশন এরর ব্যানার -->
        <div v-if="initError" class="bg-rose-600 text-white px-4 py-3 text-center text-sm font-bold shadow-md flex items-center justify-center gap-2">
          <i class="fa-solid fa-circle-exclamation text-lg animate-bounce"></i>
          <span>সার্ভার সতর্কবার্তা: {{ initError }}</span>
        </div>

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

              <button type="submit" :disabled="authLoading || initError" class="w-full bg-[#0088CC] hover:bg-[#0077B5] text-white font-bold py-3 rounded-xl text-sm shadow-md transition disabled:bg-slate-300">
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

              <!-- 7 Days OTP report -->
              <div class="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm">
                <h3 class="font-bold text-sm text-slate-800 mb-4">ওটিপি রিপোর্ট (গত ৭ দিন)</h3>
                <div class="h-32 flex items-end justify-between px-6 pt-4 border-b border-slate-100">
                  <div class="w-12 bg-[#0088CC] rounded-t-lg h-12"></div>
                  <div class="w-12 bg-slate-100 rounded-t-lg h-4"></div>
                  <div class="w-12 bg-[#0088CC] rounded-t-lg h-20"></div>
                  <div class="w-12 bg-slate-100 rounded-t-lg h-2"></div>
                  <div class="w-12 bg-slate-100 rounded-t-lg h-6"></div>
                  <div class="w-12 bg-[#0088CC] rounded-t-lg h-16"></div>
                  <div class="w-12 bg-[#0088CC] rounded-t-lg h-8"></div>
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

        const firebaseConfig = {
          apiKey: "__API_KEY__",
          authDomain: "__AUTH_DOMAIN__",
          projectId: "all-panel-support", 
          storageBucket: "__STORAGE_BUCKET__",
          messagingSenderId: "__MESSAGING_SENDER_ID__",
          appId: "__APP_ID__"
        };

        let auth = null;
        let db = null;
        let initErrorMsg = "";

        // ব্রাউজার সাইড ফায়ারবেস ইন্টিগ্রেশন সেফ-চেক
        try {
          if (!firebaseConfig.apiKey || firebaseConfig.apiKey.includes("__API_KEY__") || firebaseConfig.apiKey === "") {
            throw new Error("ফায়ারবেস API Key অনুপস্থিত। আপনার ক্লাউড হোস্টিংয়ে environment variables যুক্ত করুন।");
          }
          firebase.initializeApp(firebaseConfig);
          auth = firebase.auth();
          db = firebase.firestore();
        } catch (err) {
          console.error("Firebase Initialization Failed:", err);
          initErrorMsg = err.message || "ফায়ারবেস লোড করতে সমস্যা হয়েছে।";
        }

        createApp({
          setup() {
            const initError = ref(initErrorMsg);
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

            onMounted(() => {
              windowOrigin.value = window.location.origin; 

              if (auth && db) {
                auth.onAuthStateChanged(currentUser => {
                  if (currentUser) {
                    user.value = currentUser;

                    db.collection('profiles').doc(currentUser.uid).onSnapshot(docSnap => {
                      if (docSnap.exists) {
                        profile.value = docSnap.data();
                      }
                    });

                    db.collection('live_console').orderBy('createdAt', 'desc').limit(10).onSnapshot(snap => {
                      const logs = [];
                      snap.forEach(doc => logs.push({ id: doc.id, ...doc.data() }));
                      liveLogs.value = logs;
                    });

                    db.collection('otp_logs').where('userId', '==', currentUser.uid).orderBy('createdAt', 'desc').limit(15).onSnapshot(snap => {
                      const otps = [];
                      snap.forEach(doc => otps.push({ id: doc.id, ...doc.data() }));
                      successOtps.value = otps;
                    });

                  } else {
                    user.value = null;
                    profile.value = null;
                  }
                });
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
              if (!auth) {
                alert("ফায়ারবেস সঠিকভাবে কনফিগার করা হয়নি।");
                return;
              }
              if (!authEmail.value || !authPassword.value) return;
              authLoading.value = true;
              try {
                if (isRegistering.value) {
                  const res = await fetch('/api/v1/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: authEmail.value, password: authPassword.value })
                  });
                  const data = await res.json();
                  
                  if (data.status === 'success') {
                    await auth.signInWithEmailAndPassword(authEmail.value, authPassword.value);
                  } else {
                    alert(data.message);
                  }
                } else {
                  await auth.signInWithEmailAndPassword(authEmail.value, authPassword.value);
                }
              } catch (err) {
                alert(err.message);
              }
              authLoading.value = false;
            };

            const signOut = () => {
              if (auth) {
                auth.signOut();
              }
              activeNumber.value = null;
              otpResult.value = null;
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
              initError, user, profile, authEmail, authPassword, isRegistering, authLoading,
              currentTab, rid, activeNumber, otpResult, loadingNumber, liveLogs, successOtps, timeLeft,
              windowOrigin, handleAuth, signOut, handleGetNumber, handleCheckOtp, formatTime, window
            };
          }
        }).mount('#app');
      </script>
    </body>
    </html>
    """
    html_content = html_content.replace("__API_KEY__", os.getenv("NEXT_PUBLIC_FIREBASE_API_KEY", ""))
    html_content = html_content.replace("__AUTH_DOMAIN__", os.getenv("NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN", "all-panel-support.firebaseapp.com"))
    html_content = html_content.replace("__PROJECT_ID__", "all-panel-support")
    html_content = html_content.replace("__STORAGE_BUCKET__", "all-panel-support.appspot.com")
    html_content = html_content.replace("__MESSAGING_SENDER_ID__", os.getenv("NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID", ""))
    html_content = html_content.replace("__APP_ID__", os.getenv("NEXT_PUBLIC_FIREBASE_APP_ID", ""))

    return Response(html_content, mimetype='text/html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 4000))
    app.run(host='0.0.0.0', port=port)