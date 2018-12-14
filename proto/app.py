import tweepy
import json
import flask
from flask import Flask, render_template, Response, request, redirect, url_for, session,flash
import re
from random import randint
import config
import requests
import math
from datetime import date, timedelta
from watson_developer_cloud.natural_language_understanding_v1 import Features, EntitiesOptions, KeywordsOptions
from watson_developer_cloud import ToneAnalyzerV3
import datetime, pprint
from flask_pymongo import PyMongo
from pymongo import MongoClient   #docs: http://api.mongodb.com/python/current/index.html
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import os
from collections import OrderedDict
# from flask_oauth import OAuth

#read in stock symbols/company name csv
company_list = pd.read_csv("full.csv")

#twitter authentication - put keys in config.py & gitignore 
CONSUMER_KEY = config.consumer_key
CONSUMER_SECRET = config.consumer_secret
ACCESS_KEY = config.access_token_key
ACCESS_SECRET = config.access_token_secret

auth = tweepy.auth.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
auth.set_access_token(ACCESS_KEY, ACCESS_SECRET)
twitter_api = tweepy.API(auth)

callback_url = 'http://localhost:5000/verify'
session = {}
db = {}

#IBM Watson authentication & connnection - keys in config.py
tone_analyzer = ToneAnalyzerV3(
    version='2017-09-21',
    username = config.username2,
    password = config.password2)

stockURL = "https://www.alphavantage.co/query"

#connect to mongo server 
#create cachedtweets collection for caching 
client = MongoClient()
client = MongoClient('mongodb://app:1234@cluster0-shard-00-00-illu3.mongodb.net:27017,cluster0-shard-00-01-illu3.mongodb.net:27017,cluster0-shard-00-02-illu3.mongodb.net:27017/test?ssl=true&replicaSet=Cluster0-shard-0&authSource=admin&retryWrites=true')
db = client.database
cachedtweets = db.cachedtweets
users = db.users

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

'''
this authorizes our developer account 
'''
@app.route("/twitter")
def send_token():
    auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET, callback_url)
    redirect_url = auth.get_authorization_url()
    try:
        session['oauth_token'] = auth.request_token['oauth_token']
        session['oauth_token_secret'] = auth.request_token['oauth_token_secret']
    except tweepy.TweepError as e:
        print('Error! Failed to get request token.')

    #redirect user to twitter so they can authenticate w/ their account
    return flask.redirect(redirect_url)

@app.route("/verify")
def get_verification():
    verifier = request.args.get('oauth_verifier')
    # auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
    auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
    auth.request_token = { 'oauth_token' : session['oauth_token'],
                             'oauth_token_secret' : session['oauth_token_secret'] }

    try:
        auth.get_access_token(verifier)
        session['access_token'] = auth.access_token
        session['access_token_secret'] = auth.access_token_secret
    except tweepy.TweepError as e:
        print('e: ',e)
        print('Error! Failed to get access token.')

    auth.set_access_token(session['access_token'], session['access_token_secret'])
    api = tweepy.API(auth)
    user = api.me()
    user_str = json.dumps(user._json)
    user_info = json.loads( user_str)
    name = user_info['name']
    session['loginTwitter'] = True
    session['regLogin'] = False
    session['profile_image_url'] = user_info['profile_image_url']

    loginTwitter(user_info, session['access_token'])

    # return flask.redirect(flask.url_for('mainPage'))
    return render_template('home.html', loggedIn = True, name = name)




#this function actually gets & returns list of tweets
def getTweetsHelper(query):
    #exclude retweets & get full text of tweets 
    q = query + ' AND stock' + ' -filter:retweets'
    search_results = twitter_api.search(q, count=30, tweet_mode = 'extended', lang = 'en', result_type = 'mixed')
    tweets = []
    for tweet in search_results:
        tweet = tweet.full_text
        tweet = re.sub(r'http\S+', "", str(tweet))
        tweets.append(tweet)
    return tweets

'''
get list of tweets based on query 
if tweets for company already exist and cached time 
is less than 15 minutes from curent time, take those tweets in db and return 
else get new tweets from twitter & replace old ones in db 
'''
def getTweets(query):

    current_time = datetime.datetime.utcnow()

    #check if tweets already cached for this company 
    cache = db.cachedtweets.find_one({'company': query})

    #if company not in db at all, just get & return tweets 
    if cache is None: 
        tweets = getTweetsHelper(query)
        doc = {'company': query,
                'time'  : current_time,
                'tweets': tweets}
        db.cachedtweets.insert_one(doc)
        return tweets
    else: 
        #check if tweets in db are from within 15 mins
        #if so, return those 
        cached_time = cache['time']
        limit = cached_time + datetime.timedelta(minutes=360)
        diff = (current_time - cached_time).total_seconds()

        if diff < 900:
            return cache['tweets']

        #otherwise delete old tweets in db and lookup new tweets
        #and add to db 
        else:
            #delete old 
            cachedtweets.delete_one(cache)
            #get new tweets insert into tweet collection in db
            tweets = getTweetsHelper(query)
            doc = {'company': query,
                    'time'  : current_time,
                    'tweets': tweets}

            id_ = db.cachedtweets.insert_one(doc)
            return tweets

#compute sentiment analysis on gathered tweets 
def getSentiment(tweets):
    #convert list of tweets to one large str
    tweets = " ".join(tweets)

    tone_analysis = tone_analyzer.tone(
        {'text': tweets},
        'application/json'
    ).get_result()

    #parse json output for tones 
    result = json.loads(json.dumps(tone_analysis, indent=2))
    all_tones = result['document_tone']['tones']

    if len(all_tones) == 0: 
        all_tones = [{'score': 0.567225, 'tone_id': 'sadness', 'tone_name': 'Sadness'}, 
        {'score': 0.546128, 'tone_id': 'joy', 'tone_name': 'Joy'}]
        
    #hold tones in tuples - ex [(0.55, Sadness), (0.2, Analytical)]
    #conver tone scores to percentages 
    tones = []
    for t in all_tones: 
        name = t['tone_name']
        score = t['score']*100
        score = "{0:.2f}".format(score)     
        tones.append((name, score))
    return normalize(tones)

def normalize(tones):
    if len(tones) > 1:
        total_mag = 0
        for name,score in tones: 
            total_mag += math.sqrt(float(score)**2)

        for idx,val in enumerate(tones):
            score = val[1]
            score = (float(score)/total_mag)*100
            score = "{0:.2f}".format(score)   
            tones[idx] = (val[0], score)
    return tones
        
'''
helper function for matching stock symbols 
with their stock name 
'''
def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def getQuote(query):

    #stock market closed on weekends, so if querying on weekend, get friday value
    yesterday = date.today() - timedelta(days=1)
    if yesterday.weekday()==5: 
        yesterday = yesterday - timedelta(days=1)
    if yesterday.weekday()==6:
        yesterday = yesterday - timedelta(days=2)

    #if query is 'Apple' instead of 'AAPL'
    if query not in company_list[['Symbol']].values.tolist():
        #get symbol 
        company=company_list[company_list['Name'].str.lower().str.contains(str(query).lower())]
        if company.empty: 
            # return None
            return 'None'
        else:
            query = company['Symbol'].iloc[0]
    try:
        querystring = {"function":"TIME_SERIES_DAILY","symbol":query,"interval":"5min","apikey":"N9U9SP687FD676TQ"}
        headers = {
            'Content-Type': "application/json",
            'cache-control': "no-cache",
            'Postman-Token': "5284e93d-daa8-4884-9aff-b14c160f5a9b"
            }
        response = requests.request("GET", stockURL, headers=headers, params=querystring)
        quotes = [response.json()["Time Series (Daily)"][str(yesterday)]["4. close"]]

    #couldn't find stock/company so return error message to user 
    except KeyError as e:
        quotes = 'None'

    return quotes

def getChartData(stock, function, interval):
    if(function ==""):
        function = "TIME_SERIES_INTRADAY"
    if(interval == ""):
        interval = "1min"
    if(stock ==""):
        stock="AAPL"
    # querystring = {"function": function, "symbol": stock, "interval":interval, "apikey": "N9U9SP687FD676TQ"}
    querystring = {"function": function, "symbol": stock, "interval":interval, "apikey": config.apiKey}
    # headers = {
    #     'Content-Type': "application/json",
    #     'cache-control': "no-cache",
    #     'Postman-Token': "5284e93d-daa8-4884-9aff-b14c160f5a9b"
    # }
    headers = {
    'Content-Type': "application/json",
    'cache-control': "no-cache",
    'Postman-Token': config.Postman_Token
    }
    res = requests.get("https://www.alphavantage.co/query", params=querystring)
    return json.loads(res.text, object_pairs_hook=OrderedDict)




'''
Add user to database if user not already in database 
password is already hashed 
'''
def addUser(name, email, password):
    if userExists(email,password) == False:
        doc = {'name': name, 'email': email,'password' : password, 'watchedStocks':[]}
        db.users.insert_one(doc)
    else:
        print("User already exists!")


'''
Check if user exists in database, returns true/false
email and password must match
'''
def userExists(email, password):
    user = db.users.find_one({'email': email})
    if user is None:
        return False
    else:
        checkPassword = check_password_hash(str(user['password']), str(password))
        if checkPassword:
            return True
        else:
            return False

def userExistsTwitter(username, access_token):
    user = db.users.find_one({'email': username})
    if user is None:
        return False
    else:
        if user['password'] == access_token:
            return True
        else:
            return False

'''
login via credentials from twitter
search user db for 
'''
def loginTwitter(user, access_key_twitter):
    if userExistsTwitter(user['screen_name'], access_key_twitter):
        user = db.users.find_one({'email': user['screen_name']})
        session['name'] = user['name']
    else:
        addUser(user['name'], user['screen_name'], access_key_twitter)

    return render_template('home.html', error = False, name = user['name'], loggedIn = True)

'''
add stock to user's watch list 
'''
def watchStock(stock):
    #get user from session
    try: 
        user = db.users.find_one({'name': session['name']})
        print('user: ', user)
        if user is None: 
            return
        else: 
            users['watchedStocks'].append(stock)
    except KeyError as e: 
        return 

##########
################# ROUTES START HERE ##############################
##########


@app.route('/')
def mainPage():
    return render_template('home.html')


 #NOT STABLE RN
@app.route('/chart', methods=['get'])
def chart():
    #convert company name to symbol 'AMAZON -> 'AMZN'
    stock = request.args.get('stock')
    if stock.upper() not in company_list[['Symbol']].values.flatten().tolist():
        #get symbol
        company=company_list[company_list['Name'].str.lower().str.contains(str(stock).lower())]
        if company.empty:
            stock = 'None'
        else:
            stock = company['Symbol'].iloc[0]
    else:
        stock = stock

    function = request.args.get('function')
    if(function == "TIME_SERIES_INTRADAY"):
        interval = request.args.get('interval')
    else:
        interval = function.replace('TIME_SERIES_', '').title()

    json_data = getChartData(stock, function, interval)
    labels = []
    values = []

    if("Daily" in interval or "min" in interval):
        text = 'Time Series (%s)' % (interval)
    else:
        text = '%s Time Series' % (interval)

    for d in json_data[text]:
        labels.append(d)
        values.append(json_data[text][d]['4. close'])
    labels.reverse()
    tweets = getTweets(stock)
    tones = getSentiment(tweets)

    try:
        if session['name'] is not None or session['loggedIn']:
            loggedIn = True
            name = session['name']
            if session['loginTwitter']:
                pic_url = session['profile_image_url']
            else: 
                pic_url = url_for('static',filename='img/Blank_Avatar.png')
            return render_template('search.html', userName = name, tones = tones, labels = labels, values = values, query = stock, interval = interval, key="N9U9SP687FD676TQ", loggedIn = True,  pic_url = pic_url, tweets = tweets)
    except KeyError as e:
        loggedIn = False
        name = ""
        pic_url = url_for('static',filename='img/Blank_Avatar.png')
        return render_template('search.html', userName = name, tones = tones, labels = labels, values = values, query = stock, interval = interval, key="N9U9SP687FD676TQ", loggedIn = False,  pic_url = pic_url, tweets=tweets)


@app.route('/search', methods=['GET'])
def searchResults(): 
    query = request.args.get('query')
    tweets = getTweets(query)
    quotes = getQuote(query)
    tones = getSentiment(tweets)
    return render_template('search.html', tweets = tweets, quotes = quotes, query = query, tones = tones)

'''
method to log user in
'''
@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    if userExists(email, password):
        user = db.users.find_one({'email': email})
        session['name'] = user['name']
        session['loggedIn'] = True
        session['regLogin'] = True
        session['loginTwitter'] = False
        return render_template('home.html', name = user['name'], loggedIn = True)
    else:
        return render_template('home.html', error = True, error_message = "Credentials don't match")

'''
method for user to sign up
''' 
@app.route('/signup', methods=['POST'])
def signUp():
    if request.method == 'POST':
        email = request.form['email']
        name = request.form['name']
        pw = generate_password_hash(request.form['password'])
        addUser(name, email, pw)
        return render_template('home.html', loggedIn = True, name = name)

'''
method for user to logout 
'''
@app.route('/logout')
def logout(): 
    # remove the username from the session if it is there
    session.pop('name', None)
    return render_template('home.html', loggedIn = False)


if __name__ == '__main__':
    app.run(debug=True)
    