from flask import Flask, render_template, request, jsonify, redirect, Response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import config
import logging
import requests
import csv
import io
import time
import traceback

logging.basicConfig(
    filename='system.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# database models for tracking
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

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    sender = db.Column(db.String(50)) 
    text = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# archived models with shift_id for grouping
class ArchivedRoute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.String(100))
    driver_id = db.Column(db.Integer)
    driver_name = db.Column(db.String(100))
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    timestamp = db.Column(db.DateTime)

class ArchivedAnchor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.String(100))
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    photo_id = db.Column(db.String(100)) 
    note = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime)

class ArchivedMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.String(100))
    sender = db.Column(db.String(50)) 
    text = db.Column(db.Text)
    timestamp = db.Column(db.DateTime)

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
        name = data.get('name', f"User {tg_id[-4:]}")
        
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            driver = Driver(telegram_id=tg_id, name=name)
            db.session.add(driver)
            db.session.commit()

        if status:
            if driver.status != status and status != 'Offline':
                sys_msg = Message(driver_id=driver.id, sender="system", text=f"🔄 Status changed to: {status}")
                db.session.add(sys_msg)

            driver.status = status
            if "Issue" not in driver.status and "SOS" not in driver.status:
                driver.issue_text = None

        if is_tracking is not None:
            driver.is_tracking = bool(is_tracking)
        
        if lat and lng:
            driver.last_lat = float(lat)
            driver.last_lng = float(lng)
            if driver.status != 'Offline':
                last_point = RoutePoint.query.filter_by(driver_id=driver.id).order_by(RoutePoint.id.desc()).first()
                if not last_point or (last_point.lat != driver.last_lat or last_point.lng != driver.last_lng):
                    new_point = RoutePoint(driver_id=driver.id, lat=driver.last_lat, lng=driver.last_lng)
                    db.session.add(new_point)
        
        driver.last_update = datetime.utcnow()
        db.session.commit()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Error in update_location: {e}\n{traceback.format_exc()}")
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
            sys_msg = Message(driver_id=driver.id, sender="system", text="🚨 EMERGENCY MODE ACTIVATED")
            db.session.add(sys_msg)
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
            msg = Message(driver_id=driver.id, sender="driver", text=f"🚨 ISSUE: {data.get('issue_text')}")
            db.session.add(msg)
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
                "text": f"👨‍💻 <b>Dispatcher:</b>\n{data.get('message')}", 
                "parse_mode": "HTML"
            }
            requests.post(url, json=payload)
            msg = Message(driver_id=driver.id, sender="dispatcher", text=data.get('message'))
            db.session.add(msg)
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"error": "bad request"}), 400
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500

# chat endpoint for messages
@app.route('/api/chat_receive', methods=['POST'])
def chat_receive():
    try:
        data = request.json
        driver = Driver.query.filter_by(telegram_id=str(data.get('telegram_id'))).first()
        if driver:
            msg = Message(driver_id=driver.id, sender="driver", text=data.get('text'))
            db.session.add(msg)
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"error": "not found"}), 404
    except Exception:
        return jsonify({"error": "error"}), 500

@app.route('/api/chat_send', methods=['POST'])
def chat_send():
    try:
        data = request.json
        driver = Driver.query.get(data.get('driver_id'))
        if driver and data.get('text'):
            url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": driver.telegram_id, "text": f"👨‍💻 <b>Dispatcher:</b>\n{data.get('text')}", "parse_mode": "HTML"})
            msg = Message(driver_id=driver.id, sender="dispatcher", text=data.get('text'))
            db.session.add(msg)
            db.session.commit()
            return jsonify({"status": "success"}), 200
        return jsonify({"error": "bad request"}), 400
    except Exception:
        return jsonify({"error": "error"}), 500

@app.route('/api/get_chat/<int:driver_id>', methods=['GET'])
def get_chat(driver_id):
    messages = Message.query.filter_by(driver_id=driver_id).order_by(Message.timestamp.asc()).all()
    res = [{"sender": m.sender, "text": m.text, "time": m.timestamp.isoformat() + "Z"} for m in messages]
    return jsonify(res), 200

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
        driver = Driver.query.filter_by(telegram_id=str(data.get('telegram_id'))).first()
        if not driver:
            return jsonify({"error": "not found"}), 404
            
        shift_id = f"shift_{driver.id}_{int(time.time())}"
        
        for p in RoutePoint.query.filter_by(driver_id=driver.id).all():
            db.session.add(ArchivedRoute(shift_id=shift_id, driver_id=driver.id, driver_name=driver.name, lat=p.lat, lng=p.lng, timestamp=p.timestamp))
        for a in AnchorPoint.query.filter_by(driver_id=driver.id).all():
            db.session.add(ArchivedAnchor(shift_id=shift_id, lat=a.lat, lng=a.lng, photo_id=a.photo_id, note=a.note, timestamp=a.timestamp))
        for m in Message.query.filter_by(driver_id=driver.id).all():
            db.session.add(ArchivedMessage(shift_id=shift_id, sender=m.sender, text=m.text, timestamp=m.timestamp))
            
        RoutePoint.query.filter_by(driver_id=driver.id).delete()
        AnchorPoint.query.filter_by(driver_id=driver.id).delete()
        Message.query.filter_by(driver_id=driver.id).delete()
        
        driver.status = 'Offline'
        driver.is_tracking = False
        driver.safety_timer_end = None
        driver.issue_text = None 
        db.session.commit()
        return jsonify({"status": "archived"}), 200
    except Exception as e:
        logging.error(f"Archive error: {e}")
        return jsonify({"error": "error"}), 500

# endpoint to save visual anchors
@app.route('/api/add_anchor', methods=['POST'])
def add_anchor():
    try:
        data = request.json
        tg_id = str(data.get('telegram_id'))
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if driver:
            anchor = AnchorPoint(
                driver_id=driver.id,
                lat=data.get('lat'),
                lng=data.get('lng'),
                photo_id=data.get('photo_id'),
                note=data.get('note', 'Visual anchor')
            )
            db.session.add(anchor)
            
            sys_msg = Message(driver_id=driver.id, sender="system", text="📸 Visual Anchor created")
            db.session.add(sys_msg)
            
            driver.status = 'At Anchor'
            db.session.commit()
            return jsonify({"status": "saved"}), 200
        return jsonify({"error": "not found"}), 404
    except Exception:
        return jsonify({"error": "error"}), 500

# endpoint to delete a specific visual anchor
@app.route('/api/delete_anchor/<string:anchor_id>', methods=['DELETE'])
def delete_anchor(anchor_id):
    try:
        if str(anchor_id).startswith('arch_'):
            real_id = int(str(anchor_id).replace('arch_', ''))
            anchor = ArchivedAnchor.query.get(real_id)
        else:
            anchor = AnchorPoint.query.get(int(anchor_id))
            
        if anchor:
            db.session.delete(anchor)
            db.session.commit()
            return jsonify({"status": "deleted"}), 200
        return jsonify({"error": "not found"}), 404
    except Exception as e:
        logging.error(f"Error deleting anchor: {e}")
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
                            safety_text = "⚠️ TIMER EXPIRED!"
                        else:
                            safety_status = "active"
                            hours, remainder = divmod(remaining.total_seconds(), 3600)
                            mins, _ = divmod(remainder, 60)
                            safety_text = f"⏳ Timer: {int(hours)}h {int(mins)}m"
                    else:
                        if d.last_update and (now - d.last_update).total_seconds() > config.SAFETY_TIMEOUT_SECONDS:
                            if current_status not in ['At Anchor', 'SOS / Emergency']:
                                current_status = 'Warning (Lost Signal)'
                                safety_status = "alarm"
                                safety_text = "⚠️ SIGNAL LOST"

                route_points = RoutePoint.query.filter_by(driver_id=d.id).order_by(RoutePoint.timestamp.asc()).all()

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
                    "last_update": d.last_update.isoformat() + "Z" if d.last_update else None,
                    "route": [{"lat": p.lat, "lng": p.lng} for p in route_points]
                })
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Error fetching drivers: {e}")
        return jsonify({"error": "Failed to fetch drivers"}), 500

# api to fetch visual anchors for the map
@app.route('/api/get_anchors', methods=['GET'])
def get_anchors():
    anchors = AnchorPoint.query.all()
    archived = ArchivedAnchor.query.all()
    res = [{"id": a.id, "driver_id": a.driver_id, "lat": a.lat, "lng": a.lng, "note": a.note, "photo_id": a.photo_id} for a in anchors]
    res.extend([{"id": f"arch_{a.id}", "driver_id": "archived", "lat": a.lat, "lng": a.lng, "note": a.note, "photo_id": a.photo_id} for a in archived])
    return jsonify(res), 200

# fetches historical shifts for the analytics dropdown
@app.route('/api/get_archived_shifts', methods=['GET'])
def get_archived_shifts():
    shifts = db.session.query(ArchivedRoute.shift_id, ArchivedRoute.driver_name, db.func.min(ArchivedRoute.timestamp).label('start')).group_by(ArchivedRoute.shift_id, ArchivedRoute.driver_name).order_by(db.desc('start')).all()
    return jsonify([{"shift_id": s.shift_id, "driver_name": s.driver_name, "date": s.start.strftime("%Y-%m-%d %H:%M")} for s in shifts]), 200

# fetches all historical data for a specific shift including timestamp for route points
@app.route('/api/get_shift_history/<string:shift_id>', methods=['GET'])
def get_shift_history(shift_id):
    routes = ArchivedRoute.query.filter_by(shift_id=shift_id).order_by(ArchivedRoute.timestamp.asc()).all()
    anchors = ArchivedAnchor.query.filter_by(shift_id=shift_id).all()
    chats = ArchivedMessage.query.filter_by(shift_id=shift_id).order_by(ArchivedMessage.timestamp.asc()).all()
    
    return jsonify({
        "route": [{"lat": r.lat, "lng": r.lng, "timestamp": r.timestamp.isoformat() + "Z" if r.timestamp else None} for r in routes],
        "anchors": [{"lat": a.lat, "lng": a.lng, "note": a.note, "photo_id": a.photo_id} for a in anchors],
        "chat": [{"sender": c.sender, "text": c.text, "time": c.timestamp.isoformat() + "Z"} for c in chats]
    }), 200

# universal media fetcher (photos) proxying from telegram
@app.route('/api/get_file/<string:file_id>', methods=['GET'])
def get_file(file_id):
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getFile?file_id={file_id}"
        resp = requests.get(url).json()
        if resp.get("ok"):
            file_path = resp["result"]["file_path"]
            return redirect(f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{file_path}")
        return jsonify({"error": "File not found"}), 404
    except Exception:
        return jsonify({"error": "server error"}), 500

# endpoint to export archived routes as CSV
@app.route('/api/export_routes', methods=['GET'])
def export_routes():
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['shift_id', 'driver_name', 'lat', 'lng', 'timestamp'])
    for r in ArchivedRoute.query.all():
        cw.writerow([r.shift_id, r.driver_name, r.lat, r.lng, r.timestamp.isoformat() + "Z" if r.timestamp else ''])
    output = Response(si.getvalue(), mimetype='text/csv')
    output.headers["Content-Disposition"] = "attachment; filename=archived_routes.csv"
    return output

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host=config.SERVER_HOST, port=config.SERVER_PORT)