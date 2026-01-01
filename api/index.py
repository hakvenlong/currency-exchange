from flask import Flask, render_template, request, send_file, jsonify
import datetime
import os
import sqlite3
import requests
import platform
from fpdf import FPDF

app = Flask(__name__, template_folder='../templates')

# --- CONFIGURATION ---
if platform.system() == 'Windows':
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_FILE = os.path.join(BASE_DIR, 'exchange.db')
    INVOICE_FOLDER = os.path.join(BASE_DIR, 'invoices')
else:
    DB_FILE = '/tmp/exchange.db'
    INVOICE_FOLDER = '/tmp/invoices'

if not os.path.exists(INVOICE_FOLDER):
    try: os.makedirs(INVOICE_FOLDER)
    except: pass

SYMBOLS = {'USD': '$', 'KHR': '៛', 'THB': '฿'}

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  date TEXT, timestamp TEXT, 
                  from_curr TEXT, to_curr TEXT, 
                  amount_in REAL, amount_out REAL, 
                  rate REAL, op TEXT,
                  customer_name TEXT, market TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- HELPERS ---
def log_transaction(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("""
        INSERT INTO transactions 
        (date, timestamp, from_curr, to_curr, amount_in, amount_out, rate, op, customer_name, market) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), 
          data['from'], data['to'], data['amount'], data['total'], 
          data['rate'], data['op'], data.get('customer', ''), ''))
    conn.commit()
    conn.close()

def get_filtered_history(period='all', pair='all'):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = "SELECT * FROM transactions WHERE 1=1"
    params = []
    
    today = datetime.date.today()
    if period == 'week':
        start = today - datetime.timedelta(days=7)
        query += " AND date >= ?"
        params.append(start.strftime("%Y-%m-%d"))
    elif period == 'month':
        start = today - datetime.timedelta(days=30)
        query += " AND date >= ?"
        params.append(start.strftime("%Y-%m-%d"))
    elif period == 'year':
        start = today - datetime.timedelta(days=365)
        query += " AND date >= ?"
        params.append(start.strftime("%Y-%m-%d"))
    
    if pair != 'all':
        f, t = pair.split('_')
        query += " AND from_curr = ? AND to_curr = ?"
        params.extend([f, t])

    query += " ORDER BY id DESC LIMIT 200" # Increased limit for search
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_daily_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Get total volume per currency
    c.execute("SELECT from_curr, amount_in, to_curr, amount_out FROM transactions WHERE date = ?", (today,))
    rows = c.fetchall()
    
    # --- FIX: SMART PEOPLE COUNTING ---
    # 1. Count Guests (Empty Name) as individual people
    c.execute("SELECT COUNT(*) FROM transactions WHERE date = ? AND (customer_name IS NULL OR customer_name = '')", (today,))
    guest_count = c.fetchone()[0]
    
    # 2. Count Unique Named Customers (e.g. "John" doing 5 txns counts as 1 person)
    c.execute("SELECT COUNT(DISTINCT customer_name) FROM transactions WHERE date = ? AND customer_name != ''", (today,))
    named_count = c.fetchone()[0]
    
    total_people = guest_count + named_count
    # ----------------------------------

    conn.close()
    
    stats = {'USD': {'in': 0, 'out': 0}, 'KHR': {'in': 0, 'out': 0}, 'THB': {'in': 0, 'out': 0}}
    for r in rows:
        if r[0] in stats: stats[r[0]]['in'] += r[1]
        if r[2] in stats: stats[r[2]]['out'] += r[3]
        
    return stats, total_people
# --- PDF GENERATOR ---
def generate_pdf_invoice(data):
    now = datetime.datetime.now()
    filename = f"DPK_Invoice_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    if not os.path.exists(INVOICE_FOLDER): os.makedirs(INVOICE_FOLDER)
    path = os.path.join(INVOICE_FOLDER, filename)
    
    pdf = FPDF(format='A5')
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 20)
    pdf.cell(0, 12, 'DPK Exchange', ln=1, align='C')
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(0, 8, 'Official Receipt', ln=1, align='C')
    pdf.cell(0, 8, f"Date: {now.strftime('%d %B %Y %H:%M:%S')}", ln=1, align='C')
    
    if data.get('customer'):
        pdf.ln(2)
        pdf.cell(0, 8, f"Customer: {data['customer']}", ln=1, align='C')

    pdf.ln(5)
    pdf.line(15, pdf.get_y(), 133, pdf.get_y())
    pdf.ln(5)
    pdf.set_font("Helvetica", 'B', 14)
    pdf.cell(0, 10, 'Exchange Details', ln=1, align='C')
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 10, f"From: {data['amount']:,.2f} {data['from']}", ln=1)
    pdf.cell(0, 10, f"To:     {data['total']:,.2f} {data['to']}", ln=1)
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 10, f"Rate: 1 {data['from']} = {data['rate']:,.4f} {data['to']}", ln=1)
    pdf.ln(10)
    pdf.set_font("Helvetica", 'I', 11)
    pdf.cell(0, 10, 'Thank you!', ln=1, align='C')
    pdf.output(path)
    return filename

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
        if data['amount'] <= 0: return jsonify({'success': False, 'error': 'Invalid Amount'})
        
        if (data['from'] == 'USD' and data['to'] in ['KHR', 'THB']) or (data['from'] == 'THB' and data['to'] == 'KHR'):
            data['total'] = data['amount'] * data['rate']
            data['op'] = "×"
        else:
            data['total'] = data['amount'] / data['rate']
            data['op'] = "÷"
        data['total'] = round(data['total'], 2)
        
        log_transaction(data)
        pdf_filename = generate_pdf_invoice(data)
        return jsonify({'success': True, 'total': data['total'], 'pdf_url': f"/download/{pdf_filename}", 'op': data['op']})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

# --- NEW DELETE ROUTES ---
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

@app.route('/delete_multiple', methods=['POST'])
def delete_multiple():
    try:
        ids = request.json.get('ids', [])
        if not ids: return jsonify({'success': False, 'error': 'No IDs provided'})
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        # Use parameterized query for safety
        c.execute(f"DELETE FROM transactions WHERE id IN ({','.join(['?']*len(ids))})", ids)
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

@app.route('/update_transaction', methods=['POST'])
def update_transaction():
    try:
        d = request.json
        tx_id = d['id']
        cust = d['customer']
        amount = float(d['amount'])
        rate = float(d['rate'])
        
        f, t = d['from'], d['to']
        if (f == 'USD' and t in ['KHR', 'THB']) or (f == 'THB' and t == 'KHR'):
            total = amount * rate
        else:
            total = amount / rate
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE transactions SET customer_name=?, amount_in=?, rate=?, amount_out=? WHERE id=?", 
                 (cust, amount, rate, round(total, 2), tx_id))
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
    period = request.args.get('period', 'all')
    pair = request.args.get('pair', 'all')
    rows = get_filtered_history(period, pair)
    history_data = []
    for r in rows:
        history_data.append({
            'id': r[0], 'date': r[1], 'time': r[2],
            'from': r[3], 'to': r[4],
            'in': r[5], 'out': r[6],
            'rate': r[7], 'customer': r[9]
        })
    return jsonify(history_data)

@app.route('/download/<filename>')
def download(filename):
    path = os.path.join(INVOICE_FOLDER, filename)
    if os.path.exists(path): return send_file(path, as_attachment=True)
    return "Not Found", 404

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
        sym_from = SYMBOLS.get(d['from'], '')
        sym_to = SYMBOLS.get(d['to'], '')
        op = d.get('op', '×') 

        cust_info = ""
        if d.get('customer'): cust_info = f"\nUser: {d['customer']}"

        msg = f"""
<b>Saved Record – DPK Exchange</b>
{now}

From: {amount:,.2f} {sym_from} ({d['from']})
To: {total:,.2f} {sym_to} ({d['to']})
Rate: 1 {d['from']} = {rate:,.4f} {d['to']}
Calculation: {amount:,.2f} {op} {rate:,.4f} = {total:,.2f}{cust_info}

Saved manually from web 🌟
        """.strip()
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.json().get('ok'): return jsonify({'success': False, 'error': 'Telegram Error'})
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True)