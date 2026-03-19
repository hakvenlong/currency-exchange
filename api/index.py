from flask import Flask, render_template, request, jsonify
import datetime
import os
import sqlite3
import requests
import platform

app = Flask(__name__, template_folder='../templates')

# --- CONFIGURATION ---
if platform.system() == 'Windows':
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_FILE = os.path.join(BASE_DIR, 'exchange.db')
else:
    DB_FILE = '/tmp/exchange.db'

SYMBOLS = {'USD': '$', 'KHR': '៛', 'THB': '฿'}

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  date TEXT, timestamp TEXT, 
                  from_curr TEXT, to_curr TEXT, 
                  amount_in REAL, amount_out REAL, 
                  rate REAL, op TEXT,
                  market TEXT, fee REAL DEFAULT 0)''')
                  
    try:
        c.execute("ALTER TABLE transactions ADD COLUMN fee REAL DEFAULT 0")
    except:
        pass 
        
    c.execute('''CREATE TABLE IF NOT EXISTS balances (currency TEXT PRIMARY KEY, amount REAL)''')
    c.execute("INSERT OR IGNORE INTO balances (currency, amount) VALUES ('USD', 0), ('KHR', 0), ('THB', 0)")
    
    conn.commit()
    conn.close()

init_db()

# --- DATABASE HELPERS ---
def log_transaction(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("""
        INSERT INTO transactions 
        (date, timestamp, from_curr, to_curr, amount_in, amount_out, rate, op, market, fee) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), 
          data['from'], data['to'], data['amount'], data['total'], 
          data['rate'], data['op'], '', data['fee']))
    conn.commit()
    conn.close()

def get_filtered_history(period='day', pair='all'):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []
    
    today = datetime.date.today()
    if period == 'day':
        query += " AND date = ?"
        params.append(today.strftime("%Y-%m-%d"))
    elif period == 'week':
        start = today - datetime.timedelta(days=7)
        query += " AND date >= ?"
        params.append(start.strftime("%Y-%m-%d"))
    elif period == 'month':
        start = today - datetime.timedelta(days=30)
        query += " AND date >= ?"
        params.append(start.strftime("%Y-%m-%d"))
    
    if pair != 'all':
        f, t = pair.split('_')
        query += " AND from_curr = ? AND to_curr = ?"
        params.extend([f, t])

    query += " ORDER BY id DESC LIMIT 200"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_daily_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM transactions WHERE date = ?", (today,))
    total_people = c.fetchone()[0]
    conn.close()
    return {}, total_people

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

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
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE balances SET amount = amount + ? WHERE currency = ?", (data['amount'], data['from']))
        c.execute("UPDATE balances SET amount = amount - ? WHERE currency = ?", (data['total'], data['to']))
        if data['fee'] > 0:
            c.execute("UPDATE balances SET amount = amount + ? WHERE currency = 'KHR'", (data['fee'],))
            
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'total': data['total'], 
            'op': data['op']
        })
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/balances', methods=['GET'])
def get_balances():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT currency, amount FROM balances")
    rows = c.fetchall()
    
    # Calculate today's profit (Total fees collected today)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT SUM(fee) FROM transactions WHERE date = ?", (today,))
    profit = c.fetchone()[0] or 0
    
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
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE balances SET amount = amount + ? WHERE currency = ?", (amount, currency))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_transaction/<int:tx_id>', methods=['DELETE'])
def delete_transaction(tx_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/delete_all', methods=['DELETE'])
def delete_all():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM transactions")
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/stats')
def stats():
    data, count = get_daily_stats()
    return jsonify({'stats': data, 'count': count})

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

# --- TELEGRAM ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

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
<b>Saved Record – DPK EXCHANGE</b>
{now}

From: {amount:,.2f} {sym_from} ({d['from']})
To: {total:,.2f} {sym_to} ({d['to']})
Rate: 1 {d['from']} = {rate:,.4f} {d['to']}
Calculation: {amount:,.2f} {op} {rate:,.4f} = {total:,.2f}
        """.strip()
        
        if fee > 0:
            msg += f"\nFee: {fee:,.0f} ៛"
            
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)