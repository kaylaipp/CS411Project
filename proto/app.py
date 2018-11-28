import tweepy
import json
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

#twitter authentication - put keys in config.py & gitignore 
CONSUMER_KEY = config.consumer_key
CONSUMER_SECRET = config.consumer_secret
ACCESS_KEY = config.access_token_key
ACCESS_SECRET = config.access_token_secret
auth = tweepy.auth.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
auth.set_access_token(ACCESS_KEY, ACCESS_SECRET)
twitter_api = tweepy.API(auth)

#IBM Watson authentication & connnection - keys in config.py
tone_analyzer = ToneAnalyzerV3(
    version='2017-09-21',
    username = config.username2,
    password = config.password2)

stockURL = "https://www.alphavantage.co/query"

#connect to mongo server 
#create cachedtweets collection for caching 
client = MongoClient()
client = MongoClient('mongodb+srv://app:cs411@cluster0-illu3.mongodb.net/test?retryWrites=true')
db = client.database
cachedtweets = db.cachedtweets
users = db.users

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

@app.route('/oldindex')
def oldindex():
    return render_template('index.html')

@app.route('/')
def mainPage():
    return render_template('home.html')


#this function actually gets & returns list of tweets
def getTweetsHelper(query):
    #exclude retweets & get full text of tweets 
    q = query + ' -filter:retweets'
    search_results = twitter_api.search(q, count=10, tweet_mode = 'extended', lang = 'en')
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
        print ('Inserted data successfully')
        return tweets
    else: 
        #check if tweets in db are from within 15 mins
        #if so, return those 
        cached_time = cache['time']
        limit = cached_time + datetime.timedelta(minutes=15)
        diff = (current_time - cached_time).total_seconds()
        print('diff: ', diff)

        if diff < 900:
            print('')
            print('returning cached tweets')
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

            print('attempting to insert tweet doc')
            id_ = db.cachedtweets.insert_one(doc)
            print('id: ', id_)
            print ('Inserted data successfully')
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
        
def getQuote(query):
    yesterday = date.today() - timedelta(days=1)
    querystring = {"function":"TIME_SERIES_DAILY","symbol":query,"interval":"5min","apikey":"N9U9SP687FD676TQ"}
    headers = {
        'Content-Type': "application/json",
        'cache-control': "no-cache",
        'Postman-Token': "5284e93d-daa8-4884-9aff-b14c160f5a9b"
        }
    response = requests.request("GET", stockURL, headers=headers, params=querystring)
    quotes = [response.json()["Time Series (Daily)"][str(yesterday)]["4. close"]]
    return quotes

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
# @app.route('/login', methods=['GET','POST'])
@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    print('here')
    if userExists(email, password):
        print('here2')
        user = db.users.find_one({'email': email})
        session['name'] = user['name']
        return render_template('home.html', name = user['name'], loggedIn = True)
    print('')
    print("User doesn't exist or password is inccorect.")
    return render_template('home.html', error = True, error_message = "Credentials don't match")


@app.route('/call_modal', methods=['GET', 'POST'])
def call_modal():
    redirect(url_for('index') + '#myModal')


'''
method for user to sign up
''' 
# @app.route('/signup', methods=['GET', 'POST'])
@app.route('/signup', methods=['POST'])
def signUp():
    # email = request.args.get('email')
    # name = request.args.get('name')
    if request.method == 'POST':
        email = request.form['email']
        name = request.form['name']
        print('test: ', request.form['password_confirmation'])
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


'''
Add user to database if user not already in database 
password is already hashed 
'''
def addUser(name, email, password):
    if userExists(email,password) == False:
        doc = {'name': name, 'email': email,'password' : password}
        db.users.insert_one(doc)
        print("Sucessfully added user!")
    else:
        print("User already exists!")


'''
Check if user exists in database, returns true/false
email and password must match
'''
def userExists(email, password):
    user = db.users.find_one({'email': email})
    print('user: ', user)
    if user is None: 
        return False
    else: 
        print('password hash: ', user['password'])
        print('inputed pass:', password)
        checkPassword = check_password_hash(str(user['password']), str(password))
        print('checkPassword: ', checkPassword)
        if checkPassword:
            return True
        else: 
            return False 



if __name__ == '__main__':
    app.run(debug=true)


