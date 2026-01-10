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
    try: os.makedirs(INVOICE_FOLDER)
    except: pass

SYMBOLS = {'USD': '$', 'KHR': '៛', 'THB': '฿'}

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Removed customer_name, phone, address from schema
    c.execute('''CREATE TABLE IF NOT EXISTS transactions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  date TEXT, timestamp TEXT, 
                  from_curr TEXT, to_curr TEXT, 
                  amount_in REAL, amount_out REAL, 
                  rate REAL, op TEXT,
                  market TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- DATABASE HELPERS ---
def log_transaction(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.datetime.now()
    # Removed customer columns from INSERT
    c.execute("""
        INSERT INTO transactions 
        (date, timestamp, from_curr, to_curr, amount_in, amount_out, rate, op, market) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), 
          data['from'], data['to'], data['amount'], data['total'], 
          data['rate'], data['op'], ''))
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

    query += " ORDER BY id DESC LIMIT 200"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_daily_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT from_curr, amount_in, to_curr, amount_out FROM transactions WHERE date = ?", (today,))
    rows = c.fetchall()
    
    # Simplified count (Total transactions only)
    c.execute("SELECT COUNT(*) FROM transactions WHERE date = ?", (today,))
    total_people = c.fetchone()[0]
    
    conn.close()
    stats = {'USD': {'in': 0, 'out': 0}, 'KHR': {'in': 0, 'out': 0}, 'THB': {'in': 0, 'out': 0}}
    for r in rows:
        if r[0] in stats: stats[r[0]]['in'] += r[1]
        if r[2] in stats: stats[r[2]]['out'] += r[3]
    return stats, total_people

# --- PDF GENERATOR ---
def generate_pdf_invoice(data):
    now = datetime.datetime.now()
    filename = f"Receipt_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    path = os.path.join(INVOICE_FOLDER, filename)
    
    pdf = FPDF(format=(80, 200))
    pdf.set_margins(5, 5, 5)
    pdf.add_page()
    
    # --- HEADER ---
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 8, 'DPK EXCHANGE', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    pdf.set_font("Helvetica", '', 9)
    pdf.cell(0, 5, 'Money Exchange & Transfer', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.cell(0, 5, 'Tel: 085636898, 085203000', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    pdf.ln(3)
    pdf.set_font("Helvetica", 'B', 14)
    pdf.cell(0, 7, 'INVOICE', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.line(5, pdf.get_y(), 75, pdf.get_y())
    pdf.ln(3)

    # --- CONTENT ---
    pdf.set_font("Helvetica", '', 11)

    def print_row(label, value, bold=False):
        pdf.cell(30, 6, label, border=0)
        if bold: pdf.set_font("Helvetica", 'B', 11)
        pdf.cell(0, 6, str(value), border=0, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if bold: pdf.set_font("Helvetica", '', 11)

    print_row("Receipt No:", "690D" + now.strftime("%S"))
    print_row("Date:", now.strftime('%d/%m/%Y'))
    
    # REMOVED Customer, Phone, Addr print rows

    pdf.ln(3)
    
    sym_from = data['from']
    sym_to = data['to']
    
    print_row("Exchange:", f"{data['from']} -> {data['to']}")
    print_row("Amount In:", f"{data['amount']:,.2f} {sym_from}")
    print_row("Rate:", f"{data['rate']:,.4f}")
    
    pdf.ln(3)
    pdf.line(5, pdf.get_y(), 75, pdf.get_y())
    pdf.ln(3)
    
    # Total
    pdf.set_font("Helvetica", 'B', 14)
    pdf.cell(25, 8, "TOTAL:", border=0)
    pdf.cell(0, 8, f"{data['total']:,.2f} {sym_to}", border=0, align='R', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font("Helvetica", '', 11)
    print_row("Received:", f"{data['total']:,.2f} {sym_to}")

    # --- FOOTER ---
    pdf.ln(6)
    pdf.set_font("Helvetica", 'I', 8)
    
    start_y = pdf.get_y()
    pdf.multi_cell(0, 5, "Please check your money before leaving.\nWe are not responsible afterwards.\nThank you!", align='C')
    end_y = pdf.get_y()
    
    pdf.rect(5, start_y, 70, end_y - start_y)

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
        
        return jsonify({
            'success': True, 
            'total': data['total'], 
            'pdf_url': f"/download/{pdf_filename}", 
            'op': data['op']
        })
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

@app.route('/delete_multiple', methods=['POST'])
def delete_multiple():
    try:
        ids = request.json.get('ids', [])
        if not ids: return jsonify({'success': False, 'error': 'No IDs provided'})
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        placeholders = ','.join(['?'] * len(ids))
        c.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids)
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
        amount = float(d['amount'])
        rate = float(d['rate'])
        f, t = d['from'], d['to']
        if (f == 'USD' and t in ['KHR', 'THB']) or (f == 'THB' and t == 'KHR'):
            total = amount * rate
        else:
            total = amount / rate
            
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        # Removed customer update from SQL
        c.execute("UPDATE transactions SET amount_in=?, rate=?, amount_out=? WHERE id=?", 
                 (amount, rate, round(total, 2), tx_id))
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
        # DB Structure: id(0), date(1), time(2), from(3), to(4), in(5), out(6), rate(7), op(8), market(9)
        history_data.append({
            'id': r[0], 'date': r[1], 'time': r[2],
            'from': r[3], 'to': r[4],
            'in': r[5], 'out': r[6],
            'rate': r[7]
            # Removed customer, phone, address keys
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
        
        # Removed customer info block construction

        msg = f"""
<b>Saved Record – DPK EXCHANGE</b>
{now}

From: {amount:,.2f} {sym_from} ({d['from']})
To: {total:,.2f} {sym_to} ({d['to']})
Rate: 1 {d['from']} = {rate:,.4f} {d['to']}
Calculation: {amount:,.2f} {op} {rate:,.4f} = {total:,.2f}
        """.strip()
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.json().get('ok'): return jsonify({'success': False, 'error': 'Telegram Error'})
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)