from flask import Flask, render_template, request, redirect, url_for, session, flash
import boto3, os, smtplib
from dotenv import load_dotenv
from datetime import datetime
from botocore.exceptions import EndpointConnectionError, NoCredentialsError, ClientError
from email.message import EmailMessage

# Load environment variables
load_dotenv()

# Flask app setup
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_secret")

LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")

# Email config
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

# In-memory fallback DB class
class InMemoryTable:
    _db = {}
    def __init__(self, name, hash_key="id"):
        self.name = name
        self.hash_key = hash_key
        InMemoryTable._db.setdefault(self.name, {})

    def put_item(self, Item):
        key = Item.get(self.hash_key)
        if not key:
            raise ValueError(f"{self.hash_key} missing")
        InMemoryTable._db[self.name][key] = Item

    def get_item(self, Key):
        key = Key.get(self.hash_key)
        return {"Item": InMemoryTable._db[self.name].get(key)} if key in InMemoryTable._db[self.name] else {}

    def scan(self):
        return {"Items": list(InMemoryTable._db[self.name].values())}

# Try connecting to AWS DynamoDB
use_inmemory = False
try:
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        endpoint_url="http://localhost:8000" if LOCAL_MODE else None,
    )
    _ = list(dynamodb.tables.all())
except (EndpointConnectionError, NoCredentialsError, ClientError):
    use_inmemory = True
    dynamodb = None
    print("⚠️ Using in-memory tables.")

# Try setting up SNS
try:
    sns = boto3.client(
        "sns",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
except Exception:
    sns = None
    print("⚠️ SNS not configured.")

# Table factory
def table(name, hash_key):
    return InMemoryTable(name, hash_key) if use_inmemory else dynamodb.Table(name)

# Tables
users_table        = table("medtrack_users",        "email")
appointments_table = table("medtrack_appointments", "patient_email")
prescriptions_table= table("medtrack_prescriptions","patient_email")
reminders_table    = table("medtrack_reminders",    "patient_email")

# -----------------------------------------
# 📧 Send Email Reminder
# -----------------------------------------
def send_email_reminder(to_email, subject, message):
    try:
        msg = EmailMessage()
        msg.set_content(message)
        msg["Subject"] = subject
        msg["From"] = EMAIL_HOST_USER
        msg["To"] = to_email

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
            server.send_message(msg)
        print("📧 Email sent to", to_email)
    except Exception as e:
        print("Email error:", e)

# -----------------------------------------
# Routes
# -----------------------------------------

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]
        user_type = request.form.get("user_type")

        if users_table.get_item(Key={"email": email}).get("Item"):
            flash("User already exists.", "warning")
            return redirect(url_for("register"))

        users_table.put_item(Item={
            "email": email,
            "name": name,
            "phone": phone,
            "password": password,
            "user_type": user_type,
        })
        flash("Registration successful!", "success")
        return redirect(url_for("doctor_login" if user_type == "doctor" else "login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = users_table.get_item(Key={"email": email}).get("Item")
        if user and user["password"] == password and user["user_type"] == "patient":
            session.update({
                "user_email": user["email"],
                "user_name": user["name"],
                "user_type": "patient"
            })
            return redirect(url_for("patient_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/doctor_login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = users_table.get_item(Key={"email": email}).get("Item")
        if user and user["password"] == password and user["user_type"] == "doctor":
            session.update({
                "user_email": user["email"],
                "user_name": user["name"],
                "user_type": "doctor"
            })
            return redirect(url_for("doctor_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("doctor_login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/patient_dashboard")
def patient_dashboard():
    if session.get("user_type") != "patient":
        return redirect(url_for("login"))
    email = session["user_email"]
    all_apps = appointments_table.scan().get("Items", [])
    all_pres = prescriptions_table.scan().get("Items", [])
    appointments = [a for a in all_apps if a["patient_email"] == email]
    prescriptions = [p for p in all_pres if p["patient_email"] == email]
    return render_template("patient_dashboard.html", appointments=appointments, prescriptions=prescriptions)

@app.route("/book_appointment", methods=["GET", "POST"])
def book_appointment():
    if session.get("user_type") != "patient":
        return redirect(url_for("login"))
    if request.method == "POST":
        hour = int(request.form["hour"])
        minute = request.form["minute"]
        ampm = request.form["ampm"]
        hour_24 = hour + 12 if ampm == "PM" and hour != 12 else (0 if hour == 12 and ampm == "AM" else hour)
        time_24 = f"{hour_24:02d}:{minute}"
        appointments_table.put_item(Item={
            "patient_email": session["user_email"],
            "doctor_email": request.form["doctor_email"],
            "date": request.form["date"],
            "time": time_24,
            "reason": request.form["reason"],
            "status": "Pending",
            "prescribed": False
        })
        flash("Appointment booked", "success")
        return redirect(url_for("patient_dashboard"))
    doctors = [u for u in users_table.scan().get("Items", []) if u.get("user_type") == "doctor"]
    return render_template("appointment.html", doctors=doctors)

@app.route("/prescriptions")
def prescriptions():
    if session.get("user_type") != "patient":
        return redirect(url_for("login"))
    all = prescriptions_table.scan().get("Items", [])
    mine = [p for p in all if p["patient_email"] == session["user_email"]]
    return render_template("prescriptions.html", prescriptions=mine)

@app.route("/reminders", methods=["GET", "POST"])
def reminders():
    if session.get("user_type") != "patient":
        return redirect(url_for("login"))
    if request.method == "POST":
        message = request.form["message"]
        hour = request.form["hour"]
        minute = request.form["minute"]
        ampm = request.form["ampm"]
        time = f"{hour}:{minute} {ampm}"
        reminders_table.put_item(Item={
            "patient_email": session["user_email"],
            "message": message,
            "time": time,
        })
        # SNS & Email
        if sns and SNS_TOPIC_ARN:
            try:
                sns.publish(TopicArn=SNS_TOPIC_ARN, Subject="MedTrack+ Reminder", Message=f"{message} at {time}")
            except Exception as e:
                flash(f"SNS error: {e}", "warning")
        send_email_reminder(session["user_email"], "MedTrack+ Reminder", f"Reminder: {message} at {time}")
        flash("Reminder added", "success")
        return redirect(url_for("reminders"))
    all = reminders_table.scan().get("Items", [])
    mine = [r for r in all if r["patient_email"] == session["user_email"]]
    return render_template("reminders.html", reminders=mine)

@app.route("/patient_profile")
def patient_profile():
    if session.get("user_type") != "patient":
        return redirect(url_for("login"))
    return render_template("patient_profile.html")

@app.route("/doctor_dashboard")
def doctor_dashboard():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))
    email = session["user_email"]
    apps = appointments_table.scan().get("Items", [])
    pres = prescriptions_table.scan().get("Items", [])
    return render_template("doctor_dashboard.html",
                           appointments=[a for a in apps if a["doctor_email"] == email],
                           prescriptions=[p for p in pres if p["doctor_email"] == email],
                           today=datetime.today().strftime("%Y-%m-%d"))

@app.route("/doctor_appointments")
def doctor_appointments():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))
    data = appointments_table.scan().get("Items", [])
    return render_template("doctor_appointments.html",
                           appointments=[a for a in data if a["doctor_email"] == session["user_email"]])

@app.route("/add_prescription", methods=["GET", "POST"])
def add_prescription():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))
    patient_email = request.args.get("email")
    if request.method == "POST":
        time = f"{request.form['hour']}:{request.form['minute']} {request.form['ampm']}"
        prescriptions_table.put_item(Item={
            "patient_email": patient_email,
            "doctor_email": session["user_email"],
            "medication": request.form["medication"],
            "dosage": request.form["dosage"],
            "frequency": request.form["frequency"],
            "instructions": request.form["instructions"],
            "time": time,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        flash("Prescription added", "success")
        return redirect(url_for("doctor_dashboard"))
    return render_template("add_prescription.html", patient_email=patient_email)

@app.route("/doctor_prescriptions")
def doctor_prescriptions():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))
    all = prescriptions_table.scan().get("Items", [])
    mine = [p for p in all if p["doctor_email"] == session["user_email"]]
    return render_template("doctor_prescriptions.html", prescriptions=mine)

@app.route("/doctor_profile")
def doctor_profile():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))
    return render_template("doctor_profile.html")

if __name__ == "__main__":
    app.run(debug=True)
