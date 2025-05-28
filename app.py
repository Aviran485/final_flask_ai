from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
from werkzeug.utils import secure_filename
import tensorflow as tf
from tensorflow.keras.preprocessing import image
import numpy as np
from database import get_db_connection
from datetime import timedelta, datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.permanent_session_lifetime = timedelta(hours=1)


# Load models
DOG_VS_NOT_MODEL = tf.keras.models.load_model(r'C:\Users\avira\PycharmProjects\AI training only\new dogbreed project 93 breeds\logs\99 percent baby dogVSother.h5')
BREED_MODEL = tf.keras.models.load_model(r"C:\Users\avira\PycharmProjects\AI training only\new dogbreed project 93 breeds\logs\best_model.h5")

# Load class labels
path_of_labels = r'C:\Users\avira\ai training recent\Dog Breed Classification\train'
BREED_LABELS = [i for i in os.listdir(path_of_labels)]

@app.route('/')
def index():
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
            session.permanent = True  # 🕒 enable permanent session
            app.permanent_session_lifetime = timedelta(hours=1)  # ⏳ set timeout to 1 hour
            session['username'] = user['username']
            session['role'] = user['role']
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
                # Dog or not
                img = image.load_img(filepath, target_size=(96, 96))
                x = np.expand_dims(image.img_to_array(img) / 255.0, axis=0)
                if DOG_VS_NOT_MODEL.predict(x)[0][0] < 0.8:
                    os.remove(filepath)
                    flash("🚫 Not a dog. Please upload a valid dog image.")
                    return redirect(url_for('report'))

                # Get breed prediction
                img_breed = image.load_img(filepath, target_size=(180, 180))
                x = np.expand_dims(image.img_to_array(img_breed) / 255.0, axis=0)
                breed_pred = BREED_MODEL.predict(x)[0]
                prediction = BREED_LABELS[np.argmax(breed_pred)]

            except Exception as e:
                os.remove(filepath)
                print("🐛 AI ERROR:", e)
                flash("⚠️ Failed to process image. Try again.")
                return redirect(url_for('report'))

        # Insert into DB
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO reports (user, description, image, latitude, longitude, prediction, handled)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (
            session.get('username', 'anonymous'),
            description,
            filename,
            latitude,
            longitude,
            prediction
        ))
        conn.commit()
        flash("✅ Report submitted successfully!")
        return redirect(url_for('report'))

    return render_template('report.html')

@app.route('/reports')
def view_reports():
    if session.get('role') != 'worker':
        flash('Unauthorized')
        return redirect(url_for('index'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reports ORDER BY created_at DESC")
    reports = cur.fetchall()
    return render_template('reports.html', reports=reports)

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

@app.route('/report/<int:report_id>/edit', methods=['GET', 'POST'])
def edit_report(report_id):
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

    if request.method == 'POST':
        new_desc = request.form['description']
        new_lat = request.form.get('latitude')
        new_lon = request.form.get('longitude')
        image = request.files.get('image')

        if image and image.filename != '':
            filename = secure_filename(image.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image.save(filepath)
            cur.execute("""
                UPDATE reports SET description = ?, latitude = ?, longitude = ?, image = ?
                WHERE id = ?
            """, (new_desc, new_lat, new_lon, filename, report_id))
        else:
            cur.execute("""
                UPDATE reports SET description = ?, latitude = ?, longitude = ?
                WHERE id = ?
            """, (new_desc, new_lat, new_lon, report_id))

        conn.commit()
        flash("✅ Report updated!")
        return redirect(url_for('report_detail', report_id=report_id))

    return render_template('edit_report.html', report=report)

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

@app.route('/report/<int:report_id>/mark_handled', methods=['POST'])
def mark_handled(report_id):
    if session.get('role') != 'worker':
        flash("Unauthorized")
        return redirect(url_for('index'))

    conn = get_db_connection()
    conn.execute("UPDATE reports SET handled = 1 WHERE id = ?", (report_id,))
    conn.commit()
    flash("✅ Report marked as handled")
    return redirect(url_for('report_detail', report_id=report_id))

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

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)
