from flask import Flask, request
from tokens import TOKEN, PAGE_ACCESS_TOKEN
from flask_sqlalchemy import SQLAlchemy
import json
import fbmq
from fbmq import QuickReply, Attachment
from pprint import pprint
import random
import re 
import requests

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
db = SQLAlchemy(app)

page = fbmq.Page(PAGE_ACCESS_TOKEN)

@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if not request.args.get("hub.verify_token") == TOKEN:
            return "Verification token mismatch", 403
        return request.args["hub.challenge"], 200
    return "Hello World"

@app.route('/webhook', methods=['POST'])
def hook():
    page.handle_webhook(request.get_data(as_text=True))
    return "ok"

@page.callback(["UNLOCK_BIKE_(.+)"])
def unlock_bike(payload, event):
    match = re.search(r'(\d)+', payload)
    if not match:
        page.send(user.fb_id, "Error trying to unlock bike")
        return
    bike_id = match.group()
    user = get_user_or_signup(event.sender_id)
    bike = Bike.query.filter_by(id=bike_id).first()
    if not bike:
        page.send(user.fb_id, "Cannot find this bike")
        return
    if bike.user:
        page.send(user.fb_id, "This bike is currently signed out. Please try again later.")
        return
    if (bike.lock_combo):
        page.send(user.fb_id, "To unlock this bike, use lock combo '{}'".format(bike.lock_combo))
    user.signed_out_bike = bike
    bike.signed_out = True
    db.session.commit()
    page.send(user.fb_id, "You have successfully signed out '{}'".format(bike.name))

@page.handle_message
def process_string_message(event):
    user = get_user_or_signup(event.sender_id)
    msg_string = event.message_text
    if msg_string == "unlock bike":
        bikes = user.bikes
        if (user.signed_out_bike != None):
            page.send(user.fb_id, "Please return all bikes before signing out another one")
            return
        quick_replies = [QuickReply(title=bike.name, payload="UNLOCK_BIKE_"+str(bike.id)) for bike in bikes if not bike.signed_out]
        if (len(quick_replies) == 0):
            page.send(user.fb_id, "You do not have any bikes avaliable for rent!")
            return
        page.send(user.fb_id,
                "Which bike are you looking to unlock?",
                quick_replies = quick_replies)
    elif msg_string == "lock bike":
        bike = user.signed_out_bike
        if bike == None:
            page.send(user.fb_id,
                    "I can't seem to find a signed out bike for you")
            return
        location = QuickReply("Send Location", "LOCK_LOCATION")
        location.content_type="location"
        quick_replies = [
            location
        ]
        bike.signed_out = False
        user.past_action = "lock_bike"
        db.session.commit()
        page.send(user.fb_id,
                "Got it! Can I get the location that you're currently at?",
                quick_replies = quick_replies)
    elif len(event.message_attachments) > 0 and event.message_attachments[0].get("payload", {}).get("coordinates", False):
        coords = (event.message_attachments[0].get("payload", {}).get("coordinates", False))
        if (user.past_action ==  "lock_bike"):
            bike = user.signed_out_bike
            if bike == None:
                return
            bike.stored_lat = coords.get("lat", 0)
            bike.stored_lng = coords.get("long", 0)
            bike.signed_out = False
            user.signed_out_bike = None
            user.past_action = ""
            db.session.commit()

            page.send(user.fb_id,"Successfully locked your bike")
        elif (user.past_action ==  "find_bike"):
            google_url = "https://maps.googleapis.com/maps/api/staticmap"
            data = {}
            data["center"] = str(coords["lat"])+","+str(coords["long"])
            data["zoom"]="17"
            data["size"]="2000x2000"
            data["markers"] = []
            for bike in user.bikes:
                if not bike.signed_out:
                    data["markers"].append("color:red|{},{}".format(bike.stored_lat,bike.stored_lng))
            r = requests.get(google_url, params=data)
            user.past_action = ""
            db.session.commit()
            page.send(user.fb_id, "Here are the bikes I found near you" )
            page.send(user.fb_id, Attachment.Image(r.url))
    elif msg_string == "register bike":
        bike = Bike()
        number = int(random.random()*100)+1
        bike.name = "bike_"+str(number)
        bike.signed_out = True
        bike.signed_out_user_id = user.id
        user.bikes.append(bike)
        db.session.add(bike)
        db.session.commit()
        page.send(user.fb_id, "Registration successful. You currently have {} signed out. Please lock it back in".format(bike.name))
    elif msg_string == "find bike":
        location = QuickReply("Send Location", "FIND_LOCATION")
        location.content_type="location"
        quick_replies = [
            location
        ]
        user.past_action = "find_bike"
        db.session.commit()
        page.send(user.fb_id,
                "So you want a bike huh? Can I get the location that you're currently at?",
                quick_replies = quick_replies)
    else:
        ...

def get_user_or_signup(fb_id):
    user = User.query.filter_by(fb_id=fb_id).first()
    if user == None:
        user = User()
        user.fb_id = fb_id
        db.session.add(user)
        db.session.commit()
        page.send(user.fb_id, "Thank you for signing up!")
    return user


#Models
bike_ownership = db.Table('bike_ownership', db.Model.metadata,
        db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
        db.Column('bike_id', db.Integer, db.ForeignKey('bike.id'))
)

class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key = True, autoincrement = True)
    fb_id = db.Column(db.String(80), unique=True, nullable=False)
    stored_lat = db.Column(db.Float)
    stored_lng = db.Column(db.Float)
    past_action = db.Column(db.String(80))
    bikes = db.relationship("Bike", secondary = bike_ownership)
    signed_out_bike = db.relationship('Bike', uselist=False, back_populates="user")

class Bike(db.Model):
    __tablename__ = "bike"
    id = db.Column(db.Integer, primary_key = True, autoincrement = True)
    name = db.Column(db.String(80))
    stored_lat = db.Column(db.Float)
    stored_lng = db.Column(db.Float)
    signed_out = db.Column(db.Boolean)
    signed_out_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    lock_combo = db.Column(db.String(80))
    user = db.relationship("User", uselist=False, back_populates="signed_out_bike")

if __name__ =="__main__":
    app.run(debug=True)

