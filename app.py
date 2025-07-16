from flask import Flask, render_template, request, redirect, url_for, session, flash
import boto3
import os
from dotenv import load_dotenv
from datetime import datetime
from botocore.exceptions import EndpointConnectionError, NoCredentialsError, ClientError

load_dotenv()
LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_secret")

class InMemoryTable:
    _db = {}
    def __init__(self, name: str, hash_key: str = None):
        self.name = name
        self.hash_key = hash_key or "id"
        InMemoryTable._db.setdefault(self.name, {})

    def put_item(self, Item: dict):
        key = Item.get(self.hash_key)
        if key is None:
            raise ValueError(f"{self.hash_key} missing in Item")
        InMemoryTable._db[self.name][key] = Item

    def get_item(self, Key: dict):
        key = Key.get(self.hash_key)
        item = InMemoryTable._db[self.name].get(key)
        return {"Item": item} if item else {}

    def scan(self):
        return {"Items": list(InMemoryTable._db[self.name].values())}

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
    print("⚠️  DynamoDB not reachable – switching to in‑memory tables.")

try:
    sns = boto3.client(
        "sns",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
except Exception:
    sns = None
    print("⚠️  SNS client not configured – SNS calls will be skipped.")

SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")

def table(name, hash_key):
    if use_inmemory:
        return InMemoryTable(name, hash_key)
    return dynamodb.Table(name)

users_table        = table("medtrack_users",        "email")
appointments_table = table("medtrack_appointments", "patient_email")
prescriptions_table= table("medtrack_prescriptions","patient_email")
reminders_table    = table("medtrack_reminders",    "patient_email")

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name       = request.form["name"]
        email      = request.form["email"]
        phone      = request.form["phone"]
        password   = request.form["password"]
        user_type  = request.form.get("user_type")

        existing = users_table.get_item(Key={"email": email})
        if existing.get("Item"):
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
        email    = request.form["email"]
        password = request.form["password"]

        resp = users_table.get_item(Key={"email": email})
        user = resp.get("Item")
        if user and user["password"] == password and user["user_type"] == "patient":
            session["user_email"] = user["email"]
            session["user_name"]  = user["name"]
            session["user_type"]  = "patient"
            return redirect(url_for("patient_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/doctor_login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        email    = request.form["email"]
        password = request.form["password"]

        resp = users_table.get_item(Key={"email": email})
        user = resp.get("Item")
        if user and user["password"] == password and user["user_type"] == "doctor":
            session["user_email"] = user["email"]
            session["user_name"]  = user["name"]
            session["user_type"]  = "doctor"
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


@app.route('/book_appointment', methods=['GET', 'POST'])
def book_appointment():
    if 'user_email' not in session or session['user_type'] != 'patient':
        return redirect(url_for('login'))

    if request.method == 'POST':
        # 12-hour to 24-hour conversion
        hour_12 = int(request.form['hour'])
        minute  = request.form['minute']
        ampm    = request.form['ampm']

        if ampm == 'PM' and hour_12 != 12:
            hour_24 = hour_12 + 12
        elif ampm == 'AM' and hour_12 == 12:
            hour_24 = 0
        else:
            hour_24 = hour_12

        time_24 = f"{hour_24:02d}:{minute}"

        item = {
            'patient_email': session['user_email'],
            'doctor_email':  request.form['doctor_email'],
            'date':          request.form['date'],
            'time':          time_24,
            'reason':        request.form['reason'],
            'status':        'Pending',
            'prescribed':    False
        }
        appointments_table.put_item(Item=item)
        flash("Appointment booked", "success")
        return redirect(url_for('patient_dashboard'))

    all_users = users_table.scan().get('Items', [])
    doctors = [u for u in all_users if u.get('user_type') == 'doctor']
    return render_template('appointment.html', doctors=doctors)

@app.route("/prescriptions")
def prescriptions():
    if session.get("user_type") != "patient":
        return redirect(url_for("login"))
    data = prescriptions_table.scan().get("Items", [])
    mine = [p for p in data if p["patient_email"] == session["user_email"]]
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

        # Store in DynamoDB
        reminders_table.put_item(Item={
            "patient_email": session["user_email"],
            "message": message,
            "time": time,
        })

        # Send SNS Notification
        if sns and SNS_TOPIC_ARN:
            try:
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Message=f"Reminder: {message} at {time}",
                    Subject="MedTrack+ Reminder",
                )
            except Exception as e:
                flash(f"SNS error: {e}", "warning")

        flash("Reminder added", "success")
        return redirect(url_for("reminders"))

    # Load user's reminders
    all_items = reminders_table.scan().get("Items", [])
    mine = [r for r in all_items if r["patient_email"] == session["user_email"]]
    return render_template("reminders.html", reminders=mine)


@app.route("/patient_profile")
def patient_profile():
    if session.get("user_type") != "patient":
        return redirect(url_for("login"))
    return render_template("patient_profile.html")

from datetime import datetime

@app.route("/doctor_dashboard")
def doctor_dashboard():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))

    email = session["user_email"]
    all_apps = appointments_table.scan().get("Items", [])
    all_pres = prescriptions_table.scan().get("Items", [])

    my_apps = [a for a in all_apps if a["doctor_email"] == email]
    my_pres = [p for p in all_pres if p["doctor_email"] == email]

    today = datetime.today().strftime("%Y-%m-%d")  # Pass today's date

    return render_template(
        "doctor_dashboard.html",
        appointments=my_apps,
        prescriptions=my_pres,
        today=today
    )



@app.route('/doctor_appointments')
def doctor_appointments():
    if 'user_email' not in session or session.get('user_type') != 'doctor':
        return redirect(url_for('doctor_login'))

    data = appointments_table.scan().get('Items', [])
    my_apps = [a for a in data if a['doctor_email'] == session['user_email']]
    return render_template('doctor_appointments.html', appointments=my_apps)

@app.route("/add_prescription", methods=["GET", "POST"])
def add_prescription():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))

    patient_email = request.args.get("email")

    if request.method == "POST":
        # Get hour, minute, am/pm from form
        hour = request.form['hour']
        minute = request.form['minute']
        ampm = request.form['ampm']
        time = f"{hour}:{minute} {ampm}"

        prescriptions_table.put_item(Item={
            "patient_email": patient_email,
            "doctor_email":  session["user_email"],
            "medication":    request.form["medication"],
            "dosage":        request.form["dosage"],
            "frequency":     request.form["frequency"],
            "instructions":  request.form["instructions"],
            "time":          time,
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        flash("Prescription added", "success")
        return redirect(url_for("doctor_dashboard"))

    return render_template("add_prescription.html", patient_email=patient_email)


@app.route("/doctor_prescriptions")
def doctor_prescriptions():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))
    data = prescriptions_table.scan().get("Items", [])
    mine = [p for p in data if p["doctor_email"] == session["user_email"]]
    return render_template("doctor_prescriptions.html", prescriptions=mine)

@app.route("/doctor_profile")
def doctor_profile():
    if session.get("user_type") != "doctor":
        return redirect(url_for("doctor_login"))
    return render_template("doctor_profile.html")

if __name__ == "__main__":
    app.run(debug=True)
