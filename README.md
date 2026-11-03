# Solv: College Grievance Assistant

1. Get a free key at https://console.groq.com/keys
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your key and admin key
4. `python app.py` then open http://localhost:5000
5. Staff dashboard: http://localhost:5000/admin?key=YOUR_ADMIN_KEY

Languages: English, Telugu, Hindi, Urdu, Tamil, Kannada (add more in `LANGS` and `static/index.html`).
Ticket emails use SMTP (see `.env.example`); no extra API is needed.
Grievances are stored in `solv.db` (SQLite). The API key stays on the server, never in the browser.
For real deployment, serve over HTTPS and review who may access the data (it contains student details).
