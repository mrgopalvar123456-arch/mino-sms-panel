from flask import Flask, render_template_string

app = Flask(__name__)

# এখানে আপনার ওয়েবসাইটের HTML এবং ডিজাইন দেওয়া হয়েছে
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>জরুরি নোটিশ | mino-sms-panel</title>
    <style>
        body {
            font-family: 'Arial', sans-serif;
            background-color: #f4f6f9;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }
        .notice-container {
            background-color: #ffffff;
            border-top: 10px solid #ff4d4d;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
            border-radius: 8px;
            padding: 40px;
            max-width: 600px;
            text-align: center;
            margin: 20px;
        }
        .icon {
            font-size: 60px;
            color: #ff4d4d;
            margin-bottom: 20px;
            animation: blink 1.5s infinite;
        }
        h1 {
            color: #cc0000;
            font-size: 28px;
            margin-bottom: 20px;
        }
        p {
            color: #333333;
            font-size: 20px;
            line-height: 1.6;
            margin-bottom: 30px;
        }
        .btn {
            display: inline-block;
            background-color: #0070f3;
            color: white;
            text-decoration: none;
            padding: 12px 30px;
            font-size: 18px;
            font-weight: bold;
            border-radius: 5px;
            transition: background 0.3s ease;
        }
        .btn:hover {
            background-color: #0051b3;
        }
        @keyframes blink {
            0% { opacity: 1; }
            50% { opacity: 0.4; }
            100% { opacity: 1; }
        }
    </style>
</head>
<body>

<div class="notice-container">
    <div class="icon">📢</div>
    <h1>জরুরি নোটিশ!</h1>
    <p>
        যারা যারা ইউজার আছেন আমাদের এখানে কাজ করতেছেন, আমাদের <strong>সার্ভার চেঞ্জ করা হয়েছে</strong>। দয়া করে সবাই নতুন ডোমেইনে গিয়ে কাজ করুন।
    </p>
    <a href="https://your-new-domain.com" class="btn">নতুন সার্ভারে যান</a>
</div>

</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    app.run(debug=True)
