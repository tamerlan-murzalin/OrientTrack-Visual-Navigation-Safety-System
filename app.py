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

# init tables
with app.app_context():
    db.create_all()

# endpoint to receive data from the telegram bot
@app.route('/api/update_location', methods=['POST'])
def update_location():
    data = request.json
    if not data:
        return jsonify({"error": "no data"}), 400
    
    tg_id = str(data.get('telegram_id'))
    lat = data.get('lat')
    lng = data.get('lng')
    
    # check if we already have this driver
    driver = Driver.query.filter_by(telegram_id=tg_id).first()
    if not driver:
        # temporary name until we implement proper registration
        driver = Driver(telegram_id=tg_id, name=f"User {tg_id[-4:]}")
        db.session.add(driver)
        db.session.flush() 
    
    # update driver current state
    driver.last_lat = lat
    driver.last_lng = lng
    driver.last_update = datetime.utcnow()
    driver.status = 'Active'
    
    # log this point in the route history
    new_point = RoutePoint(driver_id=driver.id, lat=lat, lng=lng)
    db.session.add(new_point)
    
    db.session.commit()
    return jsonify({"status": "ok"}), 200

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)