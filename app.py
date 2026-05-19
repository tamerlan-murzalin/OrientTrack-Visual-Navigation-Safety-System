from flask import Flask, render_template, request, jsonify, redirect, Response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import config
import logging
import requests
import csv
import io

logging.basicConfig(
    filename='system.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Offline')
    issue_text = db.Column(db.String(255), nullable=True)
    is_tracking = db.Column(db.Boolean, default=False)
    safety_timer_end = db.Column(db.DateTime, nullable=True)
    last_lat = db.Column(db.Float)
    last_lng = db.Column(db.Float)
    last_update = db.Column(db.DateTime, default=datetime.utcnow)

class RoutePoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class AnchorPoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    photo_id = db.Column(db.String(100)) 
    note = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class ArchivedRoute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# endpoint to receive regular location updates
@app.route('/api/update_location', methods=['POST'])
def update_location():
    try:
        data = request.json
        tg_id = str(data.get('telegram_id'))
        lat = data.get('lat')
        lng = data.get('lng')
        status = data.get('status')
        is_tracking = data.get('is_tracking')
        
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            driver = Driver(telegram_id=tg_id, name=f"User {tg_id[-4:]}")
            db.session.add(driver)
            db.session.flush()

        if status:
            driver.status = status
            if "Issue" not in driver.status and "Проблема" not in driver.status:
                driver.issue_text = None
        elif driver.status == 'Offline':
            driver.status = 'Active'

        if is_tracking is not None:
            driver.is_tracking = bool(is_tracking)
        
        if lat and lng:
            driver.last_lat = lat
            driver.last_lng = lng
            if driver.status != 'Offline':
                last_point = RoutePoint.query.filter_by(driver_id=driver.id).order_by(RoutePoint.id.desc()).first()
                if not last_point or (last_point.lat != lat or last_point.lng != lng):
                    new_point = RoutePoint(driver_id=driver.id, lat=lat, lng=lng)
                    db.session.add(new_point)
        
        driver.last_update = datetime.utcnow()
        db.session.commit()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Error in update_location: {e}")
        return jsonify({"error": "Internal server error"}), 500

# check status for the bot command /status
@app.route('/api/check_status/<string:tg_id>', methods=['GET'])
def check_status(tg_id):
    try:
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            return jsonify({"status": "Unknown", "is_tracking": False}), 404
        return jsonify({
            "status": driver.status,
            "is_tracking": driver.is_tracking,
            "last_update": driver.last_update.isoformat() + "Z" if driver.last_update else None
        }), 200
    except Exception as e:
        logging.error(f"Error checking status for {tg_id}: {e}")
        return jsonify({"error": "server error"}), 500

# endpoint to update driver name/vehicle number
@app.route('/api/update_name', methods=['POST'])
def update_name():
    try:
        data = request.json
        tg_id = str(data.get('telegram_id'))
        new_name = data.get('name')
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if driver:
            driver.name = new_name
            db.session.commit()
            return jsonify({"status": "name updated"}), 200
        return jsonify({"error": "driver not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# endpoint to trigger SOS emergency mode
@app.route('/api/emergency', methods=['POST'])
def emergency():
    try:
        data = request.json
        tg_id = str(data.get('telegram_id'))
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if driver:
            driver.status = 'SOS / Emergency'
            driver.last_update = datetime.utcnow()
            db.session.commit()
            logging.warning(f"EMERGENCY TRIGGERED FOR DRIVER ID: {tg_id}")
            return jsonify({"status": "emergency registered"}), 200
        return jsonify({"error": "driver not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# receiving issue text from driver
@app.route('/api/issue', methods=['POST'])
def receive_issue():
    try:
        data = request.json
        driver = Driver.query.filter_by(telegram_id=str(data.get('telegram_id'))).first()
        if driver:
            driver.status = "Issue Reported"
            driver.issue_text = data.get('issue_text')
            driver.last_update = datetime.utcnow()
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"error": "driver not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# receiving voice messages for issues
@app.route('/api/voice', methods=['POST'])
def receive_voice():
    try:
        data = request.json
        driver = Driver.query.filter_by(telegram_id=str(data.get('telegram_id'))).first()
        if driver:
            driver.status = "Issue (Voice Report)"
            driver.issue_text = "🎙️ Voice message received"
            driver.last_update = datetime.utcnow()
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"error": "driver not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# dispatcher replying to issue via bot
@app.route('/api/reply_issue', methods=['POST'])
def reply_issue():
    try:
        data = request.json
        driver = Driver.query.get(data.get('driver_id'))
        if driver and data.get('message'):
            url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": driver.telegram_id, 
                "text": f"👨‍💻 <b>Message from dispatcher:</b>\n{data.get('message')}", 
                "parse_mode": "HTML"
            }
            requests.post(url, json=payload)
            driver.issue_text = None
            driver.status = "Active (Issue Addressed)"
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"error": "bad request"}), 400
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# handling safety timer logic
@app.route('/api/safety', methods=['POST'])
def manage_safety():
    try:
        data = request.json
        driver = Driver.query.filter_by(telegram_id=str(data.get('telegram_id'))).first()
        if driver:
            if data.get('action') == 'start':
                hours = int(data.get('hours', 0))
                minutes = int(data.get('minutes', 0))
                driver.safety_timer_end = datetime.utcnow() + timedelta(hours=hours, minutes=minutes)
            elif data.get('action') == 'stop':
                driver.safety_timer_end = None
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"error": "driver not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# endpoint to reset driver route (start new shift)
@app.route('/api/reset_route', methods=['POST'])
def reset_route():
    try:
        data = request.json
        tg_id = str(data.get('telegram_id'))
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            return jsonify({"error": "driver not found"}), 404
            
        current_points = RoutePoint.query.filter_by(driver_id=driver.id).all()
        for p in current_points:
            archive_point = ArchivedRoute(driver_id=p.driver_id, lat=p.lat, lng=p.lng, timestamp=p.timestamp)
            db.session.add(archive_point)
            
        RoutePoint.query.filter_by(driver_id=driver.id).delete()
        driver.status = 'Offline'
        driver.is_tracking = False
        driver.safety_timer_end = None
        db.session.commit()
        return jsonify({"status": "route reset"}), 200
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# endpoint to save visual anchors
@app.route('/api/add_anchor', methods=['POST'])
def add_anchor():
    try:
        data = request.json
        tg_id = str(data.get('telegram_id'))
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            return jsonify({"error": "driver not found"}), 404
            
        anchor = AnchorPoint(
            driver_id=driver.id,
            lat=data.get('lat'),
            lng=data.get('lng'),
            photo_id=data.get('photo_id'),
            note=data.get('note', 'Visual anchor')
        )
        db.session.add(anchor)
        driver.status = 'At Anchor'
        db.session.commit()
        return jsonify({"status": "anchor saved"}), 200
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# api for the frontend dashboard to fetch active drivers
@app.route('/api/get_drivers', methods=['GET'])
def get_drivers():
    try:
        drivers = Driver.query.all()
        result = []
        now = datetime.utcnow()
        
        for d in drivers:
            if d.last_lat and d.last_lng:
                if d.last_update and (now - d.last_update).total_seconds() > 43200:
                    continue

                current_status = d.status
                safety_status = "none"
                safety_text = ""

                if d.status != 'Offline':
                    if d.safety_timer_end:
                        remaining = d.safety_timer_end - now
                        if remaining.total_seconds() < 0:
                            safety_status = "alarm"
                            safety_text = "⚠️ NO SIGNAL: TIMER EXPIRED!"
                        else:
                            safety_status = "active"
                            hours, remainder = divmod(remaining.total_seconds(), 3600)
                            mins, _ = divmod(remainder, 60)
                            safety_text = f"⏳ Safety Timer: {int(hours)}h {int(mins)}m"
                    else:
                        if d.last_update and (now - d.last_update).total_seconds() > config.SAFETY_TIMEOUT_SECONDS:
                            if current_status not in ['At Anchor', 'SOS / Emergency']:
                                current_status = 'Warning (Lost Signal)'
                                safety_status = "alarm"
                                safety_text = "⚠️ SIGNAL LOST"

                result.append({
                    "id": d.id,
                    "name": d.name,
                    "status": current_status,
                    "issue_text": d.issue_text,
                    "is_tracking": d.is_tracking,
                    "safety_status": safety_status,
                    "safety_text": safety_text,
                    "lat": d.last_lat,
                    "lng": d.last_lng,
                    "last_update": d.last_update.isoformat() + "Z" if d.last_update else None
                })
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Error fetching drivers: {e}")
        return jsonify({"error": "Failed to fetch drivers"}), 500

# api to fetch the full breadcrumb trail
@app.route('/api/get_route/<int:driver_id>', methods=['GET'])
def get_route(driver_id):
    try:
        points = RoutePoint.query.filter_by(driver_id=driver_id).order_by(RoutePoint.timestamp.asc()).all()
        result = []
        for p in points:
            result.append({
                "lat": p.lat,
                "lng": p.lng,
                "time": p.timestamp.isoformat() + "Z"
            })
        return jsonify(result), 200
    except Exception as e:
        return jsonify([]), 500

# api to fetch visual anchors for the map
@app.route('/api/get_anchors', methods=['GET'])
def get_anchors():
    try:
        anchors = AnchorPoint.query.all()
        result = []
        for a in anchors:
            result.append({
                "id": a.id,
                "driver_id": a.driver_id,
                "lat": a.lat,
                "lng": a.lng,
                "note": a.note,
                "photo_id": a.photo_id
            })
        return jsonify(result), 200
    except Exception as e:
        return jsonify([]), 500

# endpoint to fetch and proxy photos from telegram
@app.route('/api/get_photo/<string:photo_id>', methods=['GET'])
def get_photo(photo_id):
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getFile?file_id={photo_id}"
        resp = requests.get(url).json()
        if resp.get("ok"):
            file_path = resp["result"]["file_path"]
            return redirect(f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{file_path}")
        return jsonify({"error": "Photo not found"}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# endpoint to export archived routes as CSV
@app.route('/api/export_routes', methods=['GET'])
def export_routes():
    try:
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['driver_id', 'lat', 'lng', 'timestamp', 'archived_at'])
        records = ArchivedRoute.query.all()
        for r in records:
            cw.writerow([
                r.driver_id, 
                r.lat, 
                r.lng, 
                r.timestamp.isoformat() + "Z" if r.timestamp else '', 
                r.archived_at.isoformat() + "Z" if r.archived_at else ''
            ])
        output = Response(si.getvalue(), mimetype='text/csv')
        output.headers["Content-Disposition"] = "attachment; filename=archived_routes.csv"
        return output
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=config.SERVER_PORT)