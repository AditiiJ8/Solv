import os, re, json, sqlite3, smtplib, threading, requests
from email.message import EmailMessage
from html import escape as esc
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("GROQ_API_KEY")
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
COLLEGE = os.getenv("COLLEGE_NAME", "Stanley College of Engineering and Technology for Women")
ADMIN_KEY = os.getenv("ADMIN_KEY", "change-me")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
URL = "https://api.groq.com/openai/v1/chat/completions"
LANGS = {"en": "English", "te": "Telugu", "hi": "Hindi", "ur": "Urdu", "ta": "Tamil", "kn": "Kannada"}
CATS = ["Academics", "Examinations", "Hostel", "Transport", "Canteen", "Library", "Infrastructure",
        "Fees & Scholarships", "Harassment or Ragging", "IT & Wi-Fi", "Other"]

SYSTEM = """You are Solv, the grievance assistant of {college}. You help students, staff and parents file and track grievances.
- Always reply in the language the user writes in. Default to {lang}. Keep replies short, polite and clear.
- To file a grievance, collect: category, a clear description, location or department, and the person's name,
  roll number or ID, a phone number, and an email address (the ticket is emailed there). One or two questions at a time. Anonymous filing is allowed:
  then skip name/roll/contact/email (the ticket ID is shown only in chat). Read the details back and get a yes before calling submit_grievance.
- After submit_grievance, give the ticket ID. If the result has email_sent_to, say a copy is being emailed to that address; if email_configured is false, say email is unavailable and ask them to note the ticket ID.
- To track, ask for the ticket ID (like SOLV-2026-0001) and call check_status. Never guess a status.
- Harassment, ragging, safety or health emergencies: set priority high, advise contacting the Internal Complaints
  Committee / college authorities or emergency services right away, and still offer to file.
- Do not invent college policies, names or deadlines. If unsure, say so and suggest the administrative office."""

TOOLS = [
 {"type": "function", "function": {"name": "submit_grievance", "description": "Register a confirmed grievance.",
  "parameters": {"type": "object", "properties": {
    "category": {"type": "string", "enum": CATS}, "summary": {"type": "string", "description": "One line, in English"},
    "details": {"type": "string"}, "location": {"type": "string"}, "name": {"type": "string"},
    "roll_no": {"type": "string"}, "contact": {"type": "string"}, "email": {"type": "string"},
    "priority": {"type": "string", "enum": ["low", "medium", "high"]}},
   "required": ["category", "summary", "details"]}}},
 {"type": "function", "function": {"name": "check_status", "description": "Look up a grievance by ticket ID.",
  "parameters": {"type": "object", "properties": {"ticket": {"type": "string"}}, "required": ["ticket"]}}}]

app = Flask(__name__, static_folder="static")

def db():
    c = sqlite3.connect("solv.db"); c.row_factory = sqlite3.Row; return c

with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS grievances(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket TEXT, category TEXT,
      summary TEXT, details TEXT, location TEXT, name TEXT, roll_no TEXT, contact TEXT, language TEXT,
      priority TEXT, status TEXT DEFAULT 'Open', created TEXT)""")
    try: c.execute("ALTER TABLE grievances ADD COLUMN email TEXT")
    except sqlite3.OperationalError: pass

def send_ticket(to, ticket, a):
    if not (SMTP_USER and SMTP_PASS): return
    rows = [("Ticket", ticket), ("Category", a.get("category", "")), ("Summary", a.get("summary", "")),
            ("Priority", a.get("priority", "medium")), ("Status", "Open"), ("Registered", datetime.now().strftime("%d %b %Y, %I:%M %p"))]
    m = EmailMessage()
    m["Subject"] = f"[{ticket}] Your grievance has been registered"
    m["From"] = f"Solv ({COLLEGE}) <{SMTP_USER}>"; m["To"] = to
    m.set_content(f"Your grievance has been registered with {COLLEGE}.\n\n" + "\n".join(f"{k}: {v}" for k, v in rows) +
                  "\n\nKeep this ticket ID. You can ask Solv for the status at any time.")
    tr = "".join(f"<tr><td style='padding:8px 0;color:#667;width:110px'>{k}</td><td style='padding:8px 0;font-weight:600'>{esc(str(v))}</td></tr>" for k, v in rows)
    m.add_alternative(f"<div style='font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#111'><h2 style='margin:0 0 4px'>Solv</h2>"
        f"<p style='color:#667;margin:0 0 20px'>{esc(COLLEGE)}</p><p>Your grievance has been registered.</p>"
        f"<div style='background:#7be37b;border-radius:10px;padding:14px 18px;font-size:20px;font-weight:700'>{esc(ticket)}</div>"
        f"<table style='width:100%;border-collapse:collapse;margin-top:12px'>{tr}</table>"
        "<p style='color:#667;font-size:13px'>Keep this ticket ID. Ask Solv for the status at any time.</p></div>", subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as srv:
            srv.starttls(); srv.login(SMTP_USER, SMTP_PASS); srv.send_message(m)
    except Exception as e:
        print("EMAIL ERROR:", e)

def run_tool(name, a, lang):
    c = db()
    if name == "submit_grievance":
        email = (a.get("email") or "").strip()
        email = email if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) else ""
        cur = c.execute("INSERT INTO grievances(category,summary,details,location,name,roll_no,contact,email,language,priority,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (a.get("category", "Other"), a.get("summary", ""), a.get("details", ""), a.get("location", ""), a.get("name", ""),
             a.get("roll_no", ""), a.get("contact", ""), email, lang, a.get("priority", "medium"), datetime.now().isoformat(timespec="seconds")))
        t = f"SOLV-{datetime.now().year}-{cur.lastrowid:04d}"
        c.execute("UPDATE grievances SET ticket=? WHERE id=?", (t, cur.lastrowid)); c.commit()
        if email: threading.Thread(target=send_ticket, args=(email, t, a), daemon=True).start()
        return {"ticket": t, "status": "Open", "email_sent_to": email or None, "email_configured": bool(SMTP_USER and SMTP_PASS)}
    r = c.execute("SELECT ticket,category,summary,status,created FROM grievances WHERE ticket=?",
                  ((a.get("ticket") or "").strip().upper(),)).fetchone()
    return dict(r) if r else {"error": "Ticket not found"}

def groq(msgs):
    r = requests.post(URL, headers={"Authorization": f"Bearer {KEY}"}, timeout=45,
        json={"model": MODEL, "messages": msgs, "tools": TOOLS, "temperature": 0.3, "max_tokens": 700})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]

@app.get("/")
def index(): return send_from_directory("static", "index.html")

@app.get("/api/config")
def config(): return jsonify(college=COLLEGE)

@app.post("/api/chat")
def chat():
    d = request.get_json(force=True)
    lang = d.get("lang", "en") if d.get("lang") in LANGS else "en"
    msgs = [{"role": "system", "content": SYSTEM.format(college=COLLEGE, lang=LANGS[lang])}]
    msgs += [{"role": m["role"], "content": str(m["content"])[:2000]} for m in d.get("messages", [])[-20:]
             if m.get("role") in ("user", "assistant")]
    try:
        msg = groq(msgs)
        for _ in range(3):
            calls = msg.get("tool_calls")
            if not calls: break
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for c in calls:
                out = run_tool(c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"), lang)
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out)})
            msg = groq(msgs)
        return jsonify(reply=msg.get("content") or "")
    except requests.HTTPError as e:
        busy = e.response is not None and e.response.status_code == 429
        return jsonify(error="Solv is busy. Please try again in a minute." if busy else "Solv could not reach the AI service."), 503
    except Exception:
        return jsonify(error="Something went wrong. Please try again."), 500

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.values.get("key") != ADMIN_KEY: return "Unauthorized", 401
    c = db()
    if request.method == "POST":
        c.execute("UPDATE grievances SET status=? WHERE ticket=?", (request.form["status"], request.form["ticket"])); c.commit()
    rows = c.execute("SELECT * FROM grievances ORDER BY id DESC").fetchall()
    body = "".join(f"<tr><td>{esc(r['ticket'] or '')}</td><td>{esc(r['created'] or '')}</td><td>{esc(r['category'])}</td>"
        f"<td>{esc(r['priority'])}</td><td><b>{esc(r['summary'])}</b><br>{esc(r['details'])}<br><small>{esc(r['location'] or '')}</small></td>"
        f"<td>{esc(r['name'] or 'Anonymous')}<br>{esc(r['roll_no'] or '')}<br>{esc(r['contact'] or '')}<br>{esc(r['email'] or '')}</td>"
        f"<td><form method=post><input type=hidden name=key value='{esc(ADMIN_KEY)}'><input type=hidden name=ticket value='{esc(r['ticket'] or '')}'>"
        f"<select name=status onchange=this.form.submit()>" + "".join(f"<option{' selected' if s == r['status'] else ''}>{s}</option>" for s in ["Open", "In Progress", "Resolved", "Closed"]) +
        "</select></form></td></tr>" for r in rows)
    return ("<meta charset=utf-8><title>Solv Admin</title><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}"
            "td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}</style><h2>Solv grievances</h2><table>"
            "<tr><th>Ticket<th>Date<th>Category<th>Priority<th>Issue<th>Raised by<th>Status</tr>" + body + "</table>")

if __name__ == "__main__":
    app.run(debug=False, port=5000)
