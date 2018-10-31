import tweepy
import json
from flask import Flask, render_template, Response, request, redirect, url_for
import re
from random import randint
import config
import requests
from datetime import date, timedelta
from watson_developer_cloud.natural_language_understanding_v1 import Features, EntitiesOptions, KeywordsOptions
from watson_developer_cloud import ToneAnalyzerV3

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
#query = "AAPL"

app = Flask(__name__)
@app.route('/oldindex')
def oldindex():
    return render_template('index.html')

@app.route('/')
def mainPage():
    return render_template('home.html')

#get list of tweets based on query 
def getTweets(query):
    #exclude retweets & get full text of tweets 
    query = query + ' -filter:retweets'
    search_results = twitter_api.search(query, count=10, tweet_mode = 'extended', lang = 'en')
    tweets = []
    for tweet in search_results:
        tweet = tweet.full_text
        tweet = re.sub(r'http\S+', "", str(tweet))
        tweets.append(tweet)
    print(tweets)
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
    print(tones)
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

if __name__ == '__main__':
    app.run()
    #sentiment()

