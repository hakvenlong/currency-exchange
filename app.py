from flask import Flask, render_template, request, send_file, jsonify
import datetime
import os
import requests
from dotenv import load_dotenv
from fpdf import FPDF

load_dotenv()

app = Flask(__name__, template_folder='../templates') 

# --- CONFIGURATION FOR VERCEL ---
# Database and Invoices must be in /tmp (Vercel Requirement)
DB_FILE = '/tmp/exchange.db'
INVOICE_FOLDER = '/tmp/invoices'

if not os.path.exists(INVOICE_FOLDER):
    os.makedirs(INVOICE_FOLDER)

# Currency symbols
SYMBOLS = {
    'USD': '$',
    'KHR': '៛',
    'THB': '฿'
}

# Telegram credentials
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    print("⚠️ WARNING: Telegram credentials missing in .env file")

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False

def generate_pdf_invoice(from_curr, to_curr, amount, total, rate, op):
    now = datetime.datetime.now()
    invoice_id = now.strftime("%Y%m%d_%H%M%S")
    filename = f"DPK_Invoice_{invoice_id}.pdf"
    full_path = os.path.join('invoices', filename)

    pdf = FPDF(format='A5')
    pdf.add_page()
    pdf.set_auto_page_break(auto=False, margin=15)

    pdf.set_font("Helvetica", 'B', 20)
    pdf.set_text_color(0, 102, 204)
    pdf.cell(0, 12, 'DPK Exchange', ln=1, align='C')

    pdf.set_font("Helvetica", '', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, 'Official Receipt', ln=1, align='C')
    pdf.ln(5)

    pdf.set_font("Helvetica", '', 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, f"Date: {now.strftime('%d %B %Y')}", ln=1, align='C')
    pdf.cell(0, 8, f"Time: {now.strftime('%H:%M:%S')}", ln=1, align='C')
    pdf.ln(8)

    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 133, pdf.get_y())
    pdf.ln(8)

    pdf.set_font("Helvetica", 'B', 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 10, 'Exchange Details', ln=1, align='C')
    pdf.ln(5)

    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 10, f"From: {amount:,.2f} {from_curr}", ln=1)
    pdf.cell(0, 10, f"To:   {total:,.2f} {to_curr}", ln=1)
    pdf.ln(5)

    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 10, f"Rate: 1 {from_curr} = {rate:,.4f} {to_curr}", ln=1)
    pdf.cell(0, 10, f"{amount:,.2f} {op} {rate:,.4f} = {total:,.2f}", ln=1)

    pdf.ln(12)

    pdf.set_font("Helvetica", 'I', 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, 'Thank you for using DPK Exchange!', ln=1, align='C')
    pdf.cell(0, 8, 'Phnom Penh, Cambodia', ln=1, align='C')

    pdf.output(full_path)
    return filename

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/exchange', methods=['POST'])
def exchange():
    try:
        data = request.get_json()
        from_curr = data['from']
        to_curr = data['to']
        amount = float(data['amount'])
        rate = float(data['rate'])

        if amount <= 0:
            return jsonify({'success': False, 'error': 'Amount must be greater than 0'})

        if (from_curr == 'USD' and to_curr in ['KHR', 'THB']) or (from_curr == 'THB' and to_curr == 'KHR'):
            total = amount * rate
            op = "×"
        else:
            total = amount / rate
            op = "÷"

        total = round(total, 2)

        pdf_filename = generate_pdf_invoice(from_curr, to_curr, amount, total, rate, op)

        return jsonify({
            'success': True,
            'total': total,
            'pdf_url': f"/download/{pdf_filename}",
            'rate': rate,
            'op': op
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/save_to_telegram', methods=['POST'])
def save_to_telegram():
    try:
        data = request.get_json()
        from_curr = data['from']
        to_curr = data['to']
        amount = data['amount']
        total = data['total']
        rate = data['rate']
        op = data['op']
        pdf_url = data['pdf_url']

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_pdf_link = request.url_root.rstrip('/') + pdf_url

        message = f"""
<b>Saved Record – DPK Exchange</b>
<i>{now_str}</i>

<b>From:</b> {amount:,.2f} {SYMBOLS.get(from_curr, from_curr)} ({from_curr})
<b>To:</b> {total:,.2f} {SYMBOLS.get(to_curr, to_curr)} ({to_curr})
<b>Rate:</b> 1 {from_curr} = {rate:,.4f} {to_curr}
<b>Calculation:</b> {amount:,.2f} {op} {rate:,.4f} = {total:,.2f}

<a href="{full_pdf_link}">📄 Download Invoice PDF</a>

Saved manually from web 🌟
        """.strip()

        success = send_telegram_message(message)

        if success:
            return jsonify({'success': True, 'message': 'Saved to Telegram!'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send to Telegram'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download/<filename>')
def download(filename):
    file_path = os.path.join('invoices', filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return "File not found", 404

if __name__ == '__main__':
    print("🚀 DPK Exchange running → http://127.0.0.1:5000")
    app.run(debug=True)