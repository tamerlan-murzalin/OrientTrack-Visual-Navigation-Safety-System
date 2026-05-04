from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)

# database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///orienttrack.db'
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
    
    return jsonify({"status": "ok"}), 200

# endpoint to save visual anchors
@app.route('/api/add_anchor', methods=['POST'])
def add_anchor():
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
    
    return jsonify({"status": "anchor saved"}), 200

# api for the frontend dashboard to fetch active drivers
@app.route('/api/get_drivers', methods=['GET'])
def get_drivers():
    drivers = Driver.query.all()
    result = []
    for d in drivers:
        # only send drivers that have coordinates
        if d.last_lat and d.last_lng:
            result.append({
                "id": d.id,
                "name": d.name,
                "status": d.status,
                "lat": d.last_lat,
                "lng": d.last_lng,
                "last_update": d.last_update.isoformat() if d.last_update else None
            })
    return jsonify(result), 200

# api to fetch visual anchors for the map
@app.route('/api/get_anchors', methods=['GET'])
def get_anchors():
    anchors = AnchorPoint.query.all()
    result = []
    for a in anchors:
        result.append({
            "id": a.id,
            "driver_id": a.driver_id,
            "lat": a.lat,
            "lng": a.lng,
            "note": a.note
        })
    return jsonify(result), 200

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)