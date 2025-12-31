from flask import Flask, render_template, request, send_file, jsonify
import datetime
import os
import sqlite3
import requests
import platform
from fpdf import FPDF
from fpdf.enums import XPos, YPos

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
    try:
        os.makedirs(INVOICE_FOLDER)
    except Exception as e:
        print(f"Warning: Could not create folder at startup: {e}")

SYMBOLS = {'USD': '$', 'KHR': '៛', 'THB': '฿'}

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, timestamp TEXT, 
                 from_curr TEXT, to_curr TEXT, amount_in REAL, amount_out REAL, 
                 rate REAL, op TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- DATABASE LOGGING ---
def log_transaction(from_curr, to_curr, amount_in, amount_out, rate, op):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.datetime.now()
    c.execute("INSERT INTO transactions (date, timestamp, from_curr, to_curr, amount_in, amount_out, rate, op) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), from_curr, to_curr, amount_in, amount_out, rate, op))
    conn.commit()
    conn.close()

def get_daily_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT from_curr, amount_in, to_curr, amount_out FROM transactions WHERE date = ?", (today,))
    rows = c.fetchall()
    conn.close()

    stats = {'USD': {'in': 0, 'out': 0}, 'KHR': {'in': 0, 'out': 0}, 'THB': {'in': 0, 'out': 0}}
    for r in rows:
        if r[0] in stats: stats[r[0]]['in'] += r[1]
        if r[2] in stats: stats[r[2]]['out'] += r[3]
    return stats, len(rows), rows

# --- PDF GENERATOR ---

def generate_pdf_invoice(from_curr, to_curr, amount, total, rate, op):
    now = datetime.datetime.now()
    filename = f"DPK_Invoice_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    
    # Ensure folder exists
    if not os.path.exists(INVOICE_FOLDER):
        os.makedirs(INVOICE_FOLDER)

    path = os.path.join(INVOICE_FOLDER, filename)
    
    pdf = FPDF(format='A5')
    pdf.add_page()
    
    # OLD SYNTAX (ln=1 instead of new_x/new_y)
    pdf.set_font("Helvetica", 'B', 20)
    pdf.cell(0, 12, 'DPK Exchange', ln=1, align='C')
    
    pdf.set_font("Helvetica", '', 10)
    pdf.cell(0, 8, 'Official Receipt', ln=1, align='C')
    pdf.cell(0, 8, f"Date: {now.strftime('%d %B %Y')}", ln=1, align='C')
    pdf.cell(0, 8, f"Time: {now.strftime('%H:%M:%S')}", ln=1, align='C')
    pdf.ln(5)
    pdf.line(15, pdf.get_y(), 133, pdf.get_y())
    pdf.ln(5)
    
    pdf.set_font("Helvetica", 'B', 14)
    pdf.cell(0, 10, 'Exchange Details', ln=1, align='C')
    
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 10, f"From: {amount:,.2f} {from_curr}", ln=1)
    pdf.cell(0, 10, f"To:     {total:,.2f} {to_curr}", ln=1)
    
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 10, f"Rate: 1 {from_curr} = {rate:,.4f} {to_curr}", ln=1)
    pdf.cell(0, 10, f"{amount:,.2f} {op} {rate:,.4f} = {total:,.2f}", ln=1)
    
    pdf.ln(10)
    pdf.set_font("Helvetica", 'I', 11)
    pdf.cell(0, 10, 'Thank you for using DPK Exchange!', ln=1, align='C')
    
    pdf.output(path)
    return filename

# ... rest of code ...

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/exchange', methods=['POST'])
def exchange():
    try:
        data = request.json
        from_curr, to_curr = data['from'], data['to']
        amount, rate = float(data['amount']), float(data['rate'])
        
        if amount <= 0: return jsonify({'success': False, 'error': 'Invalid Amount'})

        if (from_curr == 'USD' and to_curr in ['KHR', 'THB']) or (from_curr == 'THB' and to_curr == 'KHR'):
            total = amount * rate
            op = "×"
        else:
            total = amount / rate
            op = "÷"
        total = round(total, 2)
        
        log_transaction(from_curr, to_curr, amount, total, rate, op)
        pdf_filename = generate_pdf_invoice(from_curr, to_curr, amount, total, rate, op)

        return jsonify({'success': True, 'total': total, 'pdf_url': f"/download/{pdf_filename}", 'op': op})
    except Exception as e:
        print(f"EXCHANGE ERROR: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stats')
def stats():
    data, count, history = get_daily_stats()
    return jsonify({'stats': data, 'count': count, 'history': [{'from': h[0], 'in': h[1], 'to': h[2], 'out': h[3]} for h in history]})

@app.route('/download/<filename>')
def download(filename):
    file_path = os.path.join(INVOICE_FOLDER, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return "File not found", 404

# --- TELEGRAM BOT ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

@app.route('/save_to_telegram', methods=['POST'])
def save_to_telegram():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return jsonify({'success': False, 'error': 'Telegram not configured'})
    
    try:
        data = request.json
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format Values
        amount_val = float(data['amount'])
        total_val = float(data['total'])
        rate_val = float(data['rate'])
        
        sym_from = SYMBOLS.get(data['from'], '')
        sym_to = SYMBOLS.get(data['to'], '')

        # Build Message (PDF Link Removed)
        msg = f"""
<b>Saved Record – DPK Exchange</b>
<i>{now_str}</i>

<b>From:</b> {amount_val:,.2f} {sym_from} ({data['from']})
<b>To:</b> {total_val:,.2f} {sym_to} ({data['to']})
<b>Rate:</b> 1 {data['from']} = {rate_val:,.4f} {data['to']}
<b>Calculation:</b> {amount_val:,.2f} {data.get('op', '×')} {rate_val:,.4f} = {total_val:,.2f}

Saved manually from web 🌟
        """.strip()

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        
        requests.post(url, json=payload, timeout=5)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print(f"🚀 App Started. Saving invoices to: {INVOICE_FOLDER}")
    app.run(debug=True)