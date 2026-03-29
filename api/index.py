from flask import Flask, render_template, request, jsonify
import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from dotenv import load_dotenv

# Find and load the exact path for local testing
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(BASE_DIR, '.env.development.local')
    load_dotenv(env_path)
except:
    pass

app = Flask(__name__, template_folder='../templates')

# --- DATABASE CONNECTION ---
def get_db_connection():
    # Force load environment variables
    load_dotenv() 
    
    db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
    
    if not db_url:
        # This will stop the app and tell you exactly what is wrong
        raise ConnectionError("Environment variable DATABASE_URL is NOT found. "
                             "Check your .env file or Vercel settings.")

    # Fix for some providers using 'postgres://' which newer SQLAlchemy/Psycopg2 dislikes
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    return psycopg2.connect(db_url)

SYMBOLS = {'USD': '$', 'KHR': '៛', 'THB': '฿'}

# --- DATABASE SETUP ---
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Create transactions table
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id SERIAL PRIMARY KEY, 
                  date TEXT, timestamp TEXT, 
                  from_curr TEXT, to_curr TEXT, 
                  amount_in REAL, amount_out REAL, 
                  rate REAL, op TEXT,
                  market TEXT, fee REAL DEFAULT 0)''')
                  
    # Create balances table
    c.execute('''CREATE TABLE IF NOT EXISTS balances (currency TEXT PRIMARY KEY, amount REAL)''')
    c.execute("INSERT INTO balances (currency, amount) VALUES ('USD', 0) ON CONFLICT (currency) DO NOTHING")
    c.execute("INSERT INTO balances (currency, amount) VALUES ('KHR', 0) ON CONFLICT (currency) DO NOTHING")
    c.execute("INSERT INTO balances (currency, amount) VALUES ('THB', 0) ON CONFLICT (currency) DO NOTHING")
    
    # Create rates table for persistent F5 refresh
    c.execute('''CREATE TABLE IF NOT EXISTS rates (pair TEXT PRIMARY KEY, rate REAL)''')
    default_rates = [('usd_khr', 4008), ('usd_thb', 31.44), ('khr_usd', 4021), ('khr_thb', 127.6), ('thb_usd', 31.82), ('thb_khr', 127.6)]
    for pair, rate in default_rates:
        c.execute("INSERT INTO rates (pair, rate) VALUES (%s, %s) ON CONFLICT (pair) DO NOTHING", (pair, rate))

    conn.commit()
    c.close()
    conn.close()

# Initialize tables securely on startup
try:
    init_db()
except Exception as e:
    print("Database init error:", e)

# --- DATABASE HELPERS ---
def log_transaction(data):
    conn = get_db_connection()
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("""
        INSERT INTO transactions 
        (date, timestamp, from_curr, to_curr, amount_in, amount_out, rate, op, market, fee) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), 
          data['from'], data['to'], data['amount'], data['total'], 
          data['rate'], data['op'], '', data['fee']))
    conn.commit()
    c.close()
    conn.close()

def get_filtered_history(period='day', pair='all'):
    conn = get_db_connection()
    c = conn.cursor()
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []
    
    today = datetime.date.today()
    if period == 'day':
        query += " AND date = %s"
        params.append(today.strftime("%Y-%m-%d"))
    elif period == 'week':
        start = today - datetime.timedelta(days=7)
        query += " AND date >= %s"
        params.append(start.strftime("%Y-%m-%d"))
    elif period == 'month':
        start = today - datetime.timedelta(days=30)
        query += " AND date >= %s"
        params.append(start.strftime("%Y-%m-%d"))
    
    if pair != 'all':
        f, t = pair.split('_')
        query += " AND from_curr = %s AND to_curr = %s"
        params.extend([f, t])

    query += " ORDER BY id DESC LIMIT 200"
    c.execute(query, tuple(params))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

def get_all_stats():
    conn = get_db_connection()
    c = conn.cursor()
    today = datetime.date.today()
    week_start = today - datetime.timedelta(days=7)
    month_start = today - datetime.timedelta(days=30)
    
    # Day Customers
    c.execute("SELECT COUNT(*) FROM transactions WHERE date = %s", (today.strftime("%Y-%m-%d"),))
    day_count = c.fetchone()[0]
    
    # Week Customers
    c.execute("SELECT COUNT(*) FROM transactions WHERE date >= %s", (week_start.strftime("%Y-%m-%d"),))
    week_count = c.fetchone()[0]
    
    # Month Customers
    c.execute("SELECT COUNT(*) FROM transactions WHERE date >= %s", (month_start.strftime("%Y-%m-%d"),))
    month_count = c.fetchone()[0]
    
    c.close()
    conn.close()
    return {'day': day_count, 'week': week_count, 'month': month_count}

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/rates', methods=['GET'])
def get_rates():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT pair, rate FROM rates")
    rates = {row[0]: row[1] for row in c.fetchall()}
    c.close()
    conn.close()
    return jsonify(rates)

@app.route('/update_rates', methods=['POST'])
def update_rates():
    try:
        data = request.json
        conn = get_db_connection()
        c = conn.cursor()
        for pair, rate in data.items():
            c.execute("UPDATE rates SET rate = %s WHERE pair = %s", (float(rate), pair))
        conn.commit()
        c.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e: 
        return jsonify({'success': False, 'error': str(e)})

@app.route('/exchange', methods=['POST'])
def exchange():
    try:
        data = request.json
        data['amount'] = float(data['amount'])
        data['rate'] = float(data['rate'])
        data['fee'] = float(data.get('fee', 0))
        
        if data['amount'] <= 0: return jsonify({'success': False, 'error': 'Invalid Amount'})
        
        if (data['from'] == 'USD' and data['to'] in ['KHR', 'THB']) or (data['from'] == 'THB' and data['to'] == 'KHR'):
            data['total'] = data['amount'] * data['rate']
            data['op'] = "×"
        else:
            data['total'] = data['amount'] / data['rate']
            data['op'] = "÷"
        data['total'] = round(data['total'], 2)
        
        log_transaction(data)
        
        # Update Balances
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE balances SET amount = amount + %s WHERE currency = %s", (data['amount'], data['from']))
        c.execute("UPDATE balances SET amount = amount - %s WHERE currency = %s", (data['total'], data['to']))
        if data['fee'] > 0:
            c.execute("UPDATE balances SET amount = amount + %s WHERE currency = 'KHR'", (data['fee'],))
            
        conn.commit()
        c.close()
        conn.close()
        
        return jsonify({
            'success': True, 
            'total': data['total'], 
            'op': data['op']
        })
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/balances', methods=['GET'])
def get_balances():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT currency, amount FROM balances")
    rows = c.fetchall()
    
    # Calculate today's profit
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT SUM(fee) FROM transactions WHERE date = %s", (today,))
    profit_result = c.fetchone()[0]
    profit = profit_result if profit_result is not None else 0
    
    c.close()
    conn.close()
    
    data = {row[0]: row[1] for row in rows}
    data['PROFIT_KHR'] = profit
    return jsonify(data)

@app.route('/update_balance', methods=['POST'])
def update_balance():
    try:
        data = request.json
        currency = data['currency']
        amount = float(data['amount'])
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE balances SET amount = amount + %s WHERE currency = %s", (amount, currency))
        conn.commit()
        c.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_transaction/<int:tx_id>', methods=['DELETE'])
def delete_transaction(tx_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM transactions WHERE id = %s", (tx_id,))
        conn.commit()
        c.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_all', methods=['DELETE'])
def delete_all():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM transactions")
        conn.commit()
        c.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/stats')
def stats():
    data = get_all_stats()
    return jsonify(data)

# --- TELEGRAM ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

@app.route('/history')
def history_route():
    period = request.args.get('period', 'day')
    pair = request.args.get('pair', 'all')
    rows = get_filtered_history(period, pair)
    history_data = []
    for r in rows:
        fee = r[10] if len(r) > 10 else 0
        history_data.append({
            'id': r[0], 'date': r[1], 'time': r[2],
            'from': r[3], 'to': r[4],
            'in': r[5], 'out': r[6],
            'rate': r[7], 'fee': fee
        })
    return jsonify(history_data)
@app.route('/save_to_telegram', methods=['POST'])
def save_to_telegram():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        return jsonify({'success': False, 'error': 'Telegram Token or Chat ID missing'})
    try:
        d = request.json
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        amount = float(d['amount'])
        total = float(d['total'])
        rate = float(d['rate'])
        fee = float(d.get('fee', 0))
        sym_from = SYMBOLS.get(d['from'], '')
        sym_to = SYMBOLS.get(d['to'], '')
        op = d.get('op', '×') 

        msg = f"""
<b>🏦 វិក្កយបត្រ – DPK EXCHANGE</b>
📅 {now}

📤 <b>ប្រាក់ប្តូរ:</b> {amount:,.2f} {sym_from} ({d['from']})
📥 <b>ទទួលបាន:</b> {total:,.2f} {sym_to} ({d['to']})
📊 <b>អត្រាប្តូរប្រាក់:</b> 1 {d['from']} = {rate:,.4f} {d['to']}
🧮 <b>ការគណនា:</b> {amount:,.2f} {op} {rate:,.4f} = {total:,.2f}
        """.strip()
        
        if fee > 0:
            msg += f"\n💸 <b>សេវាកម្ម (Fee):</b> {fee:,.0f} ៛"
            
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})
    
if __name__ == '__main__':
    app.run(debug=True, port=5000)