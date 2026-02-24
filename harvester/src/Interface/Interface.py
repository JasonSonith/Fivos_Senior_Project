from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import uuid
import datetime

app = FastAPI(title="Fivos AI Control Center")

# ==============================
# In-Memory Storage
# ==============================

users = {
    "admin": {"password": "admin123", "role": "Administrator"},
    "reviewer": {"password": "review123", "role": "Reviewer"}
}

sessions = {}
runs = []
logs = []

discrepancies = [
    {
        "id": "DISC-001",
        "manufacturer": "Acme Medical",
        "device": "FlexCat 12Fr",
        "field": "Overall Length",
        "severity": "High",
        "confidence": 0.86,
        "gudid": "40 cm",
        "manufacturer_value": "45 cm",
        "status": "Pending",
        "audit": []
    }
]

# ==============================
# Utilities
# ==============================

def log_event(msg):
    logs.append({
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "message": msg
    })

def get_user():
    return sessions.get("active_user")

# ==============================
# Modern Layout
# ==============================

def layout(content):

    return f"""
    <html>
    <head>
        <title>Fivos AI</title>
        <style>
            body {{
                margin:0;
                font-family:'Segoe UI', Arial;
                background: radial-gradient(circle at 20% 10%, #111827, #0b0f19 70%);
                color:#e5e7eb;
                display:flex;
            }}

            .sidebar {{
                width:260px;
                height:100vh;
                background:#0f172a;
                padding:35px 20px;
                border-right:1px solid #1f2937;
            }}

            .logo {{
                font-size:22px;
                font-weight:bold;
                margin-bottom:45px;
                color:#22d3ee;
                letter-spacing:1px;
            }}

            .nav a {{
                display:block;
                padding:12px;
                margin-bottom:14px;
                border-radius:10px;
                text-decoration:none;
                color:#cbd5e1;
                border:1px solid #1f2937;
                transition:0.25s;
            }}

            .nav a:hover {{
                border-color:#22d3ee;
                background:#111827;
                box-shadow:0 0 15px rgba(34,211,238,0.3);
                color:white;
            }}

            .main {{
                flex:1;
                padding:60px;
            }}

            .card {{
                background: linear-gradient(145deg,#111827,#1f2937);
                padding:30px;
                border-radius:20px;
                margin-bottom:35px;
                border:1px solid #1f2937;
                transition:0.25s;
            }}

            .card:hover {{
                border-color:#22d3ee;
                box-shadow:0 0 20px rgba(34,211,238,0.15);
            }}

            .btn {{
                padding:10px 18px;
                border-radius:12px;
                border:1px solid #22d3ee;
                background:transparent;
                color:#22d3ee;
                font-weight:bold;
                cursor:pointer;
                transition:0.25s;
                text-decoration:none;
                display:inline-block;
            }}

            .btn:hover {{
                background:#22d3ee;
                color:black;
                box-shadow:0 0 15px rgba(34,211,238,0.5);
            }}

            .btn-danger {{
                border-color:#ef4444;
                color:#ef4444;
            }}

            .btn-danger:hover {{
                background:#ef4444;
                color:white;
            }}

            table {{
                width:100%;
                border-collapse:collapse;
            }}

            th, td {{
                padding:16px;
                border-bottom:1px solid #1f2937;
            }}

            th {{
                color:#94a3b8;
                text-align:left;
            }}

            tr:hover {{
                background:#111827;
            }}

            .badge {{
                padding:5px 10px;
                border-radius:8px;
                font-size:12px;
                font-weight:bold;
            }}

            .pending {{
                background:#facc15;
                color:black;
            }}

            .resolved {{
                background:#10b981;
                color:black;
            }}

            select, textarea {{
                width:100%;
                padding:10px;
                border-radius:12px;
                border:1px solid #1f2937;
                background:#0f172a;
                color:white;
                margin-bottom:15px;
            }}

            h2 {{
                margin-top:0;
            }}
        </style>
    </head>
    <body>

        <div class="sidebar">
            <div class="logo">⚡ Fivos AI</div>
            <div class="nav">
                <a href="/">Overview</a>
                <a href="/runs">Agents</a>
                <a href="/discrepancies">Review Queue</a>
                <a href="/reports">Analytics</a>
                <a href="/admin">Admin</a>
                <a href="/logs">System Logs</a>
                <a href="/logout">Logout</a>
            </div>
        </div>

        <div class="main">
            {content}
        </div>

    </body>
    </html>
    """

# ==============================
# Root Fix (NO MORE 404)
# ==============================

@app.get("/", response_class=HTMLResponse)
def home():
    return layout("""
        <div class="card">
            <h2>System Overview</h2>
            <p>Pending Issues: """ + str(len([d for d in discrepancies if d["status"] == "Pending"])) + """</p>
            <p>Total Agent Runs: """ + str(len(runs)) + """</p>
        </div>
    """)

# ==============================
# Login
# ==============================

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <body style="margin:0;background:radial-gradient(circle,#111827,#0b0f19);display:flex;align-items:center;justify-content:center;height:100vh;font-family:Segoe UI;">
        <div style="background:linear-gradient(145deg,#111827,#1f2937);padding:50px;border-radius:20px;border:1px solid #1f2937;width:350px;">
            <h2 style="color:#22d3ee;text-align:center;margin-bottom:30px;">Fivos AI Login</h2>
            <form method="post">
                <input name="username" placeholder="Username" style="width:100%;padding:12px;border-radius:12px;border:1px solid #1f2937;background:#0f172a;color:white;margin-bottom:20px;">
                <input name="password" type="password" placeholder="Password" style="width:100%;padding:12px;border-radius:12px;border:1px solid #1f2937;background:#0f172a;color:white;margin-bottom:30px;">
                <button type="submit" style="width:100%;padding:12px;border-radius:12px;border:1px solid #22d3ee;background:transparent;color:#22d3ee;font-weight:bold;">Login</button>
            </form>
        </div>
    </body>
    """

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    if username in users and users[username]["password"] == password:
        sessions["active_user"] = username
        return RedirectResponse("/", status_code=302)
    return "Invalid credentials"

@app.get("/logout")
def logout():
    sessions.clear()
    return RedirectResponse("/login", status_code=302)

# ==============================
# Agents
# ==============================

@app.get("/runs", response_class=HTMLResponse)
def runs_page():
    rows = ""
    for r in runs:
        rows += f"<tr><td>{r['id']}</td><td>{r['type']}</td><td>{r['time']}</td></tr>"

    return layout(f"""
        <div class="card">
            <h2>AI Agents</h2>
            <a href="/run/harvest" class="btn">Run Harvester</a>
            <a href="/run/validate" class="btn">Run Validator</a>
            <br><br>
            <table>
                <tr><th>ID</th><th>Agent</th><th>Time</th></tr>
                {rows}
            </table>
        </div>
    """)

@app.get("/run/{rtype}")
def run_agent(rtype: str):
    runs.append({
        "id": str(uuid.uuid4())[:8],
        "type": rtype,
        "time": datetime.datetime.now().strftime("%H:%M:%S")
    })
    log_event(f"{rtype} agent executed")
    return RedirectResponse("/runs", status_code=302)

# ==============================
# Review Queue
# ==============================

@app.get("/discrepancies", response_class=HTMLResponse)
def review_queue():
    rows = ""
    for d in discrepancies:
        status_class = "pending" if d["status"] == "Pending" else "resolved"
        rows += f"""
        <tr>
            <td>{d['id']}</td>
            <td>{d['manufacturer']}</td>
            <td>{d['field']}</td>
            <td>{int(d['confidence']*100)}%</td>
            <td><span class="badge {status_class}">{d['status']}</span></td>
            <td><a href="/review/{d['id']}" class="btn">Review</a></td>
        </tr>
        """

    return layout(f"""
        <div class="card">
            <h2>AI Validation Review Queue</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Manufacturer</th>
                    <th>Field</th>
                    <th>Confidence</th>
                    <th>Status</th>
                    <th></th>
                </tr>
                {rows}
            </table>
        </div>
    """)

# ==============================
# Review Page
# ==============================

@app.get("/review/{disc_id}", response_class=HTMLResponse)
def review_page(disc_id: str):
    d = next((x for x in discrepancies if x["id"] == disc_id), None)

    return layout(f"""
        <div class="card">
            <h2>Review {d['id']}</h2>
            <p><b>Field:</b> {d['field']}</p>
            <p><b>GUDID:</b> {d['gudid']}</p>
            <p><b>Manufacturer:</b> {d['manufacturer_value']}</p>

            <form method="post">
                <select name="decision">
                    <option>Approve</option>
                    <option>Reject</option>
                </select>

                <textarea name="notes" placeholder="Add reviewer notes..."></textarea>

                <button class="btn">Submit Decision</button>
            </form>
        </div>
    """)

@app.post("/review/{disc_id}")
def submit_review(disc_id: str, decision: str = Form(...), notes: str = Form("")):
    d = next((x for x in discrepancies if x["id"] == disc_id), None)
    d["status"] = "Resolved"
    d["audit"].append({
        "decision": decision,
        "notes": notes,
        "time": datetime.datetime.now().strftime("%H:%M:%S")
    })
    return RedirectResponse("/discrepancies", status_code=302)

# ==============================
# Run Server
# ==============================

if __name__ == "__main__":
    uvicorn.run("Interface:app", host="127.0.0.1", port=8000, reload=True)
