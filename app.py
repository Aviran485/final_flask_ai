from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
from werkzeug.utils import secure_filename
import tensorflow as tf
from tensorflow.keras.preprocessing import image
import numpy as np
from database import get_db_connection
from datetime import timedelta, datetime
from io import BytesIO
from collections import Counter

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.permanent_session_lifetime = timedelta(hours=1)

DOG_VS_NOT_MODEL = tf.keras.models.load_model(
    r'C:\Users\avira\PycharmProjects\AI training only\new dogbreed project 93 breeds\logs\99 percent baby dogVSother.h5')
BREED_MODEL = tf.keras.models.load_model(
    r"C:\Users\avira\PycharmProjects\AI training only\new dogbreed project 93 breeds\logs\best_model.h5")
BREED_LABELS = [i for i in os.listdir(r'C:\Users\avira\ai training recent\Dog Breed Classification\train')]


@app.route('/')
def index():
    if session.get('role') in ['worker', 'admin']:
        return redirect(url_for('view_reports'))
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
        user = cur.fetchone()
        if user:
            if user['role'] in ['worker', 'admin'] and user['dormant']:
                flash("This account is currently dormant.")
                return redirect(url_for('login'))
            session.permanent = True
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] in ['worker', 'admin']:
                return redirect(url_for('view_reports'))
            else:
                return redirect(url_for('index'))
        flash('Invalid login')
    return render_template('login.html')





@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/report', methods=['GET', 'POST'])
def report():
    if request.method == 'POST':
        description = request.form['description']
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        image_file = request.files['image']
        prediction = "Unknown"
        filename = "no-image.jpg"

        if image_file:
            filename = secure_filename(image_file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(filepath)
            try:
                img = image.load_img(filepath, target_size=(96, 96))
                x = np.expand_dims(image.img_to_array(img) / 255.0, axis=0)
                if DOG_VS_NOT_MODEL.predict(x)[0][0] < 0.8:
                    os.remove(filepath)
                    flash("🚫 Not a dog. Please upload a valid dog image.")
                    return redirect(url_for('report'))
                img_breed = image.load_img(filepath, target_size=(180, 180))
                x = np.expand_dims(image.img_to_array(img_breed) / 255.0, axis=0)
                breed_pred = BREED_MODEL.predict(x)[0]
                prediction = BREED_LABELS[np.argmax(breed_pred)]
            except Exception as e:
                os.remove(filepath)
                flash("⚠️ Failed to process image. Try again.")
                return redirect(url_for('report'))

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reports (description, image, latitude, longitude, prediction, handled)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (description, filename, latitude, longitude, prediction))
        conn.commit()
        flash("✅ Report submitted successfully!")
        return redirect(url_for('report'))

    return render_template('report.html')


@app.route('/reports', methods=['GET', 'POST'])
def view_reports():
    if session.get('role') not in ['worker', 'admin']:
        flash('Unauthorized')
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    start = request.form.get('start')
    end = request.form.get('end')
    handled_status = request.form.get('handled_status')
    worker_filter = request.form.get('worker')

    query = "SELECT * FROM reports WHERE 1=1"
    params = []

    if start and end:
        query += " AND created_at BETWEEN ? AND ?"
        params.extend([start, end])

    if handled_status == 'handled':
        query += " AND handled = 1"
    elif handled_status == 'unhandled':
        query += " AND handled = 0"

    if worker_filter and worker_filter != 'all':
        query += " AND handled_by = ?"
        params.append(worker_filter)

    query += " ORDER BY created_at DESC"
    cur.execute(query, params)
    reports = cur.fetchall()

    cur.execute("SELECT DISTINCT handled_by FROM reports WHERE handled_by IS NOT NULL")
    workers = [row['handled_by'] for row in cur.fetchall()]

    total = len(reports)
    handled_count = sum(1 for r in reports if r['handled'] == 1)
    unhandled_count = total - handled_count

    breed_counter = Counter(r['prediction'] for r in reports if r['prediction'] and r['prediction'] != "Unknown")

    filters = {
        'start': start or '',
        'end': end or '',
        'handled_status': handled_status or 'all',
        'worker': worker_filter or 'all'
    }

    return render_template(
        'reports.html',
        reports=reports,
        workers=workers,
        stats={
            'total': total,
            'handled': handled_count,
            'unhandled': unhandled_count,
            'predictions': dict(breed_counter)
        },
        filters=filters
    )



@app.route('/report/<int:report_id>')
def report_detail(report_id):
    if session.get('role') != 'worker':
        flash('Unauthorized')
        return redirect(url_for('index'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    report = cur.fetchone()
    if not report:
        flash("Report not found")
        return redirect(url_for('view_reports'))
    return render_template("report_detail.html", report=report)


@app.route('/report/<int:report_id>/mark_handled', methods=['POST'])
def mark_handled(report_id):
    if session.get('role') != 'worker':
        flash("Unauthorized")
        return redirect(url_for('index'))
    conn = get_db_connection()
    conn.execute("UPDATE reports SET handled = 1, handled_at = ?, handled_by = ? WHERE id = ?",
                 (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['username'], report_id))
    conn.commit()
    flash("✅ Report marked as handled")
    return redirect(url_for('report_detail', report_id=report_id))


@app.route('/report/<int:report_id>/delete', methods=['POST'])
def delete_report(report_id):
    if session.get('role') != 'worker':
        flash("Unauthorized")
        return redirect(url_for('index'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT image FROM reports WHERE id = ?", (report_id,))
    result = cur.fetchone()
    if result and result['image']:
        path = os.path.join(app.config['UPLOAD_FOLDER'], result['image'])
        if os.path.exists(path):
            os.remove(path)
    cur.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    flash("🗑️ Report deleted")
    return redirect(url_for('view_reports'))


@app.route('/report/<int:report_id>/edit', methods=['GET', 'POST'])
def edit_report(report_id):
    if session.get('role') != 'worker':
        flash("Unauthorized")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        description = request.form['description']
        latitude = request.form['latitude']
        longitude = request.form['longitude']
        cur.execute("""
            UPDATE reports
            SET description = ?, latitude = ?, longitude = ?
            WHERE id = ?
        """, (description, latitude, longitude, report_id))
        conn.commit()
        flash("✏️ Report updated successfully")
        return redirect(url_for('report_detail', report_id=report_id))

    cur.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    report = cur.fetchone()
    if not report:
        flash("Report not found")
        return redirect(url_for('view_reports'))

    return render_template("edit_report.html", report=report)

@app.route('/recognition', methods=['GET', 'POST'])
def recognition():
    if request.method == 'POST':
        image_file = request.files['image']
        if image_file:
            filename = secure_filename(image_file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(filepath)

            try:
                img_dvn = image.load_img(filepath, target_size=(96, 96))
                x = np.expand_dims(image.img_to_array(img_dvn) / 255.0, axis=0)
                if DOG_VS_NOT_MODEL.predict(x)[0][0] < 0.8:
                    return render_template('recognition.html', result="Not a Dog", image=filename)

                img_breed = image.load_img(filepath, target_size=(180, 180))
                x = np.expand_dims(image.img_to_array(img_breed) / 255.0, axis=0)
                breed_pred = BREED_MODEL.predict(x)[0]
                prediction = BREED_LABELS[np.argmax(breed_pred)]

                return render_template('recognition.html', result=prediction, image=filename)
            except Exception as e:
                print("🐛 RECOGNITION ERROR:", e)
                flash("AI error during recognition.")
                return redirect(url_for('recognition'))

    return render_template('recognition.html')



@app.route('/add_worker', methods=['GET', 'POST'])
def add_worker():
    if session.get('role') != 'admin':
        flash("Unauthorized – Admins only")
        return redirect(url_for('index'))

    if request.method == 'POST':
        new_username = request.form['username']
        new_password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("INSERT INTO users (username, password, role, dormant) VALUES (?, ?, 'worker', 0)",
                        (new_username, new_password))
            conn.commit()
            flash("✅ New worker created successfully")
        except:
            flash("❌ Username already exists or invalid data")

        return redirect(url_for('add_worker'))

    return render_template('add_worker.html')


@app.route('/manage_workers', methods=['GET', 'POST'])
def manage_workers():
    if session.get('role') != 'admin':
        flash("Unauthorized")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role = 'worker'")
    workers = cur.fetchall()
    return render_template('manage_workers.html', workers=workers)


@app.route('/toggle_dormant/<string:username>', methods=['POST'])
def toggle_dormant(username):
    if session.get('role') != 'admin':
        flash("Unauthorized")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT dormant FROM users WHERE username = ?", (username,))
    user = cur.fetchone()

    if user:
        new_status = 0 if user['dormant'] else 1
        cur.execute("UPDATE users SET dormant = ? WHERE username = ?", (new_status, username))
        conn.commit()
        flash(f"🔁 Updated '{username}' dormant status.")
    return redirect(url_for('manage_workers'))


@app.route('/delete_worker/<string:username>', methods=['POST'])
def delete_worker(username):
    if session.get('role') != 'admin':
        flash("Unauthorized")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    flash(f"🗑️ Worker '{username}' deleted.")
    return redirect(url_for('manage_workers'))



@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)
