from flask import Flask, render_template, request, jsonify, redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import config # importing our centralized configuration
import logging # importing the logging library for server monitoring
import requests # required to fetch photos from Telegram API

# setup logging to a file
logging.basicConfig(
    filename='system.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

app = Flask(__name__)

# database setup using config
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# models for tracking
class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Offline')
    last_lat = db.Column(db.Float)
    last_lng = db.Column(db.Float)
    last_update = db.Column(db.DateTime, default=datetime.utcnow)

class RoutePoint(db.Model):
    # storing coordinates for the leaflet map path
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class AnchorPoint(db.Model):
    # visual anchors for precise unloading locations
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    photo_id = db.Column(db.String(100)) 
    note = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# init tables
with app.app_context():
    db.create_all()

# endpoint to receive regular location updates
@app.route('/api/update_location', methods=['POST'])
def update_location():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "no data"}), 400
        
        tg_id = str(data.get('telegram_id'))
        lat = data.get('lat')
        lng = data.get('lng')
        
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            driver = Driver(telegram_id=tg_id, name=f"User {tg_id[-4:]}")
            db.session.add(driver)
            db.session.flush() 
        
        driver.last_lat = lat
        driver.last_lng = lng
        driver.last_update = datetime.utcnow()
        driver.status = 'Active'
        
        new_point = RoutePoint(driver_id=driver.id, lat=lat, lng=lng)
        db.session.add(new_point)
        db.session.commit()
        
        # log successful update
        logging.info(f"Location update successful for driver ID: {tg_id}")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        # log errors if database or payload fails
        logging.error(f"Error in update_location: {e}")
        return jsonify({"error": "Internal server error"}), 500

# check status for the bot command /status
@app.route('/api/check_status/<string:tg_id>', methods=['GET'])
def check_status(tg_id):
    try:
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            return jsonify({"status": "Unknown", "message": "Driver not registered"}), 404
        
        return jsonify({
            "status": driver.status,
            "last_update": driver.last_update.isoformat() if driver.last_update else None
        }), 200
    except Exception as e:
        logging.error(f"Error checking status for {tg_id}: {e}")
        return jsonify({"error": "server error"}), 500

# endpoint to update driver name/vehicle number
@app.route('/api/update_name', methods=['POST'])
def update_name():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "no data"}), 400
            
        tg_id = str(data.get('telegram_id'))
        new_name = data.get('name')
        
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        if not driver:
            return jsonify({"error": "driver not found"}), 404
            
        driver.name = new_name
        db.session.commit()
        
        logging.info(f"Name updated to {new_name} for driver ID: {tg_id}")
        return jsonify({"status": "name updated"}), 200
    except Exception as e:
        logging.error(f"Error in update_name: {e}")
        return jsonify({"error": "Internal server error"}), 500

# endpoint to trigger SOS emergency mode
@app.route('/api/emergency', methods=['POST'])
def emergency():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "no data"}), 400
            
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
        logging.error(f"Error in emergency endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500

# endpoint to reset driver route (start new shift)
@app.route('/api/reset_route', methods=['POST'])
def reset_route():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "no data"}), 400
            
        tg_id = str(data.get('telegram_id'))
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        
        if not driver:
            return jsonify({"error": "driver not found"}), 404
            
        # delete all route points to clear the map for a new shift
        RoutePoint.query.filter_by(driver_id=driver.id).delete()
        driver.status = 'Active'
        db.session.commit()
        
        logging.info(f"Route history reset for driver ID: {tg_id}")
        return jsonify({"status": "route reset"}), 200
    except Exception as e:
        logging.error(f"Error in reset_route: {e}")
        return jsonify({"error": "Internal server error"}), 500

# endpoint to save visual anchors
@app.route('/api/add_anchor', methods=['POST'])
def add_anchor():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "no data"}), 400
            
        tg_id = str(data.get('telegram_id'))
        driver = Driver.query.filter_by(telegram_id=tg_id).first()
        
        if not driver:
            return jsonify({"error": "driver not found"}), 404
            
        anchor = AnchorPoint(
            driver_id=driver.id,
            lat=data.get('lat'),
            lng=data.get('lng'),
            photo_id=data.get('photo_id'),
            note=data.get('note', 'Arrived at anchor')
        )
        
        db.session.add(anchor)
        driver.status = 'At Anchor'
        db.session.commit()
        
        logging.info(f"Anchor successfully saved for driver ID: {tg_id}")
        return jsonify({"status": "anchor saved"}), 200
    except Exception as e:
        logging.error(f"Error in add_anchor: {e}")
        return jsonify({"error": "Internal server error"}), 500

# api for the frontend dashboard to fetch active drivers
@app.route('/api/get_drivers', methods=['GET'])
def get_drivers():
    try:
        drivers = Driver.query.all()
        result = []
        now = datetime.utcnow() # get current time for safety check
        
        for d in drivers:
            if d.last_lat and d.last_lng:
                # skip drivers who haven't updated in over 12 hours (43200 seconds)
                if d.last_update and (now - d.last_update).total_seconds() > 43200:
                    continue

                current_status = d.status
                
                # safety timer logic: use timeout variable from config
                if d.last_update and (now - d.last_update).total_seconds() > config.SAFETY_TIMEOUT_SECONDS:
                    if current_status != 'At Anchor' and current_status != 'SOS / Emergency':
                        current_status = 'Warning (Lost Signal)'

                result.append({
                    "id": d.id,
                    "name": d.name,
                    "status": current_status,
                    "lat": d.last_lat,
                    "lng": d.last_lng,
                    "last_update": d.last_update.isoformat() if d.last_update else None
                })
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Error fetching drivers: {e}")
        return jsonify({"error": "Failed to fetch drivers"}), 500

# api to fetch the full breadcrumb trail for a specific driver
@app.route('/api/get_route/<int:driver_id>', methods=['GET'])
def get_route(driver_id):
    try:
        points = RoutePoint.query.filter_by(driver_id=driver_id).order_by(RoutePoint.timestamp.asc()).all()
        result = []
        for p in points:
            result.append({
                "lat": p.lat,
                "lng": p.lng,
                "time": p.timestamp.isoformat()
            })
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Error fetching route for driver {driver_id}: {e}")
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
        logging.error(f"Error fetching anchors: {e}")
        return jsonify([]), 500

# endpoint to fetch and proxy photos from telegram for the dashboard
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
        logging.error(f"Error fetching photo {photo_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # now using port from config
    app.run(debug=True, port=config.SERVER_PORT)