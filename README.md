# 💱 DPK Exchange System

A professional, modern currency exchange dashboard built with **Flask (Python)**. Designed for money changers in Cambodia to manage daily transactions, print receipts, and track profit/loss in real-time.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Flask](https://img.shields.io/badge/framework-Flask-green.svg)

## ✨ Key Features

* **⚡ Real-time Conversion:** Instant calculation for USD, KHR (Riel), and THB (Baht).
* **🎨 Modern UI:** Glassmorphism design with Dark/Light mode support.
* **🖨️ Thermal Printing:** Auto-formatted receipts optimized for 80mm thermal printers.
* **📊 Profit & Loss Tracking:** Tracks "Cash In" vs. "Cash Out" to calculate daily balance.
* **📄 PDF Invoicing:** Generates downloadable PDF receipts for customers.
* **📱 Telegram Integration:** One-click save to send transaction details to a Telegram group.
* **🌍 Multi-language:** Full support for English (🇺🇸), Khmer (🇰🇭), and Chinese (🇨🇳).
* **🛠️ Admin Control:** Manually adjust exchange rates on the fly.

## 🚀 Installation & Setup

Follow these steps to run the project locally on your computer.

### 1. Clone the Repository
```bash
git clone [https://github.com/YOUR_USERNAME/dpk-exchange.git](https://github.com/YOUR_USERNAME/dpk-exchange.git)
cd dpk-exchange
2. Install Dependencies
Make sure you have Python installed.

Bash

pip install -r requirements.txt
3. Configure Environment
Create a .env file in the root folder to set up your Telegram bot (optional):

Ini, TOML

TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
4. Run the App
Bash

python app.py
The app will start at http://127.0.0.1:5000.

📦 Deployment
Option 1: PythonAnywhere / Render (Recommended)
Since this app uses SQLite to save transaction history, it is best hosted on platforms with persistent storage like PythonAnywhere.

Upload files.

Install requirements.

Run! Your database (exchange.db) remains safe.

Option 2: Vercel (Demo Only)
You can host on Vercel, but database history will be wiped every time the server restarts because Vercel is serverless/read-only.

Update app.py to save DB to /tmp/exchange.db.

Connect GitHub repo to Vercel.

📂 Project Structure
dpk-exchange/
├── invoices/           # Generated PDF receipts
├── static/             # CSS/Images (if any)
├── templates/
│   └── index.html      # Main Dashboard UI
├── app.py              # Main Flask Backend & Logic
├── exchange.db         # SQLite Database (Auto-created)
├── requirements.txt    # Python Dependencies
├── vercel.json         # Vercel Configuration
└── README.md           # Documentation
🛡️ Technologies Used
Backend: Python, Flask, SQLite

Frontend: HTML5, Bootstrap 5, JavaScript

PDF Engine: FPDF

Fonts: Plus Jakarta Sans, Noto Sans Khmer
