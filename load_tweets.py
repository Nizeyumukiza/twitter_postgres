#!/usr/bin/python3

# imports
import sqlalchemy
import os
import datetime
import zipfile
import io
import json

################################################################################
# helper functions
################################################################################


def remove_nulls(s):
    r'''
    Postgres doesn't support strings with the null character \x00 in them, but twitter does.
    This helper function replaces the null characters with an escaped version so that they can be loaded into postgres.
    Technically, this means the data in postgres won't be an exact match of the data in twitter,
    and there is no way to get the original twitter data back from the data in postgres.

    The null character is extremely rarely used in real world text (approx. 1 in 1 billion tweets),
    and so this isn't too big of a deal.
    A more correct implementation, however, would be to *escape* the null characters rather than remove them.
    This isn't hard to do in python, but it is a bit of a pain to do with the JSON/COPY commands for the denormalized data.
    Since our goal is for the normalized/denormalized versions of the data to match exactly,
    we're not going to escape the strings for the normalized data.

    >>> remove_nulls('\x00')
    ''
    >>> remove_nulls('hello\x00 world')
    'hello world'
    '''
    if s is None:
        return None
    else:
        return s.replace('\x00','')


def get_id_urls(url, connection):
    '''
    Given a url, return the corresponding id in the urls table.
    If no row exists for the url, then one is inserted automatically.

    NOTE:
    This function cannot be tested with standard python testing tools because it interacts with the db.
    '''
    sql = sqlalchemy.sql.text('''
    insert into urls 
        (url)
        values
        (:url)
    on conflict do nothing
    returning id_urls
    ;
    ''')
    res = connection.execute(sql,{'url':url}).first()

    # when no conflict occurs, then the query above inserts a new row in the url table and returns id_urls in res[0];
    # when a conflict occurs, then the query above does not insert or return anything;
    # we need to run a select statement to put the already existing id_urls into res[0]
    if res is None:
        sql = sqlalchemy.sql.text('''
        select id_urls 
        from urls
        where
            url=:url
        ''')
        res = connection.execute(sql,{'url':url}).first()

    id_urls = res[0]
    return id_urls


def insert_tweet(connection,tweet):
    '''
    Insert the tweet into the database.

    Args:
        connection: a sqlalchemy connection to the postgresql db
        tweet: a dictionary representing the json tweet object

    NOTE:
    This function cannot be tested with standard python testing tools because it interacts with the db.
    
    FIXME:
    This function is only partially implemented.
    You'll need to add appropriate SQL insert statements to get it to work.
    '''

    # skip tweet if it's already inserted
    sql=sqlalchemy.sql.text('''
    SELECT id_tweets 
    FROM tweets
    WHERE id_tweets = :id_tweets
    ''')
    res = connection.execute(sql,{
        'id_tweets':tweet['id'],
        })
   # connection.commit()

    if res.first() is not None:
        return

    # insert tweet within a transaction;
    # this ensures that a tweet does not get "partially" loaded
    with connection.begin() as trans:

        ########################################
        # insert into the users table
        ########################################
        if tweet['user']['url'] is None:
            user_id_urls = None
        else:
            user_id_urls = get_id_urls(tweet['user']['url'], connection)
        
        # create/update the user
        # check if the user already exist
        user = tweet.get('user',{})

        sql_check_user_id=sqlalchemy.sql.text('''
         SELECT id_users
         FROM users
         WHERE id_users = :id_users
         ''')
        res = connection.execute(sql_check_user_id,{
            'id_users':user['id'],
        })

        sql_insert = sqlalchemy.sql.text('''
        insert into users
            (id_users, created_at, updated_at, id_urls, friends_count,
            listed_count, favourites_count, statuses_count, protected, verified,
            screen_name, name, location, description, withheld_in_countries)
            values
            (:id_users, :created_at, :updated_at, :id_urls, :friends_count,
            :listed_count, :favourites_count, :statuses_count, :protected, :verified,
            :screen_name, :name,:location, :description, :withheld_in_countries)
        on conflict do nothing
        ;
        ''')

        sql_update = sqlalchemy.sql.text('''
        update users
        set
         id_users = :id_users,
         created_at = :created_at, 
         updated_at = :updated_at, 
         id_urls = :id_urls, 
         friends_count = :friends_count,
         listed_count = :listed_count,
         favourites_count = :favourites_count,
         statuses_count = :statuses_count,
         protected = :protected,
         verified = :verified,
         screen_name = :screen_name,
         name = :name,
         location = :location,
         description = :description,
         withheld_in_countries = :withheld_in_countries
        where id_users = :id_users
        ;
        ''')
        
        if res.first() is not None:
            sql = sql_update
        else:
            sql = sql_insert
        data = {
                'id_users':user.get('id', None),
                'created_at':user.get('created_at', None),
                'updated_at':user.get('updated_at',None),
                'id_urls':user_id_urls,
                'friends_count':user.get('friends_count', 0),
                'listed_count':user.get('listed_count',0),
                'favourites_count':user.get('favourites_count',0),
                'statuses_count':user.get('statuses_count',0),
                'protected':user.get('protected',False),
                'verified':user.get('verified',False),
                'screen_name':remove_nulls(user.get('screen_name',None)),
                'name':remove_nulls(user.get('name',None)),
                'location':remove_nulls(user.get('location',None)),
                'description':remove_nulls(user.get('description',None)),
                'withheld_in_countries':remove_nulls(tweet.get('withheld_in_countries',None))
         }
        res= connection.execute(sql, data)

        ########################################
        # insert into the tweets table
        ########################################
        
        geo =''
        try:
            geo_coords = tweet['geo']['coordinates']
            geo_coords = str(tweet['geo']['coordinates'][0]) + ' ' + str(tweet['geo']['coordinates'][1])
            geo_str = 'POINT'
            geo = geo_str+'('+geo_coords+')'
        except TypeError:
            try:
                geo_coords = '('
                for i,poly in enumerate(tweet['place']['bounding_box']['coordinates']):
                    if i>0:
                        geo_coords+=','
                    geo_coords+='('
                    for j,point in enumerate(poly):
                        geo_coords+= str(point[0]) + ' ' + str(point[1]) + ','
                    geo_coords+= str(poly[0][0]) + ' ' + str(poly[0][1])
                    geo_coords+=')'
                geo_coords+=')'
                geo_str = 'MULTIPOLYGON'
                geo  = 'POLYGON' + geo_coords
            except KeyError:
                if tweet['user']['geo_enabled']:
                    geo_str = None
                    geo_coords = None
                    geo = geo_str

        try:
            text = tweet['extended_tweet']['full_text']
        except:
            text = tweet['text']

        try:
            country_code = tweet['place']['country_code'].lower()
        except TypeError:
            country_code = None

        if country_code == 'us':
            state_code = tweet['place']['full_name'].split(',')[-1].strip().lower()
            if len(state_code)>2:
                state_code = None
        else:
            state_code = None

        try:
            place_name = tweet['place']['full_name']
        except TypeError:
            place_name = None

        # NOTE:
        # The tweets table has the following foreign key:
        # > FOREIGN KEY (in_reply_to_user_id) REFERENCES users(id_users)
        #
        # This means that every "in_reply_to_user_id" field must reference a valid entry in the users table.
        # If the id is not in the users table, then you'll need to add it in an "unhydrated" form.
        if tweet.get('in_reply_to_user_id',None) is not None:
            res_id_in_users = connection.execute(sql_check_user_id,
                    {'id_users':tweet.get('in_reply_to_user_id'),})
            
            if res_id_in_users.first() is  None:

                sql_id_insert=sqlalchemy.sql.text('''
                insert into users
                    (id_users)
                    values
                    (:id_users)
                on conflict do nothing
                ;
                ''')

                res_insert = connection.execute(sql_id_insert, {'id_users':tweet.get('in_reply_to_user_id'),})

        # insert the tweet
        sql_in_tweets=sqlalchemy.sql.text(f'''
           insert into tweets
           (id_tweets, id_users, created_at, in_reply_to_status_id,
           in_reply_to_user_id, quoted_status_id,
           retweet_count, favorite_count,
           quote_count, withheld_copyright,
           withheld_in_countries, source, text,
           country_code, state_code,
           lang, place_name, geo)
           values
          (:id_tweets, :id_users, :created_at, :in_reply_to_status_id,
           :in_reply_to_user_id, :quoted_status_id,
           :retweet_count, :favorite_count,
           :quote_count, :withheld_copyright,
           :withheld_in_countries, :source, :text,
           :country_code, :state_code,
           :lang, :place_name, :geo) 
           on conflict do nothing
           ;
        ''')
        data = {
                'id_tweets':tweet.get('id',None),
                'id_users':user.get('id',None),
                'created_at':tweet.get('created_at',None),
                'in_reply_to_status_id': tweet.get('in_reply_to_status_id', None),
                'in_reply_to_user_id':tweet.get('in_reply_to_user_id',None),
                'quoted_status_id':tweet.get('quoted_status_id',None),
                'retweet_count':tweet.get('retweet_count',0),
                'favorite_count':tweet.get('favorite_count',0),
                'quote_count':tweet.get('quote_count',0),
                'withheld_copyright':tweet.get('withheld_copyright',False),
                'withheld_in_countries':tweet.get('withheld_in_countries',None),
                'source':remove_nulls(tweet.get('source',None)),
                'text':remove_nulls(text),
                'country_code':country_code,
                'state_code':state_code,
                'lang':remove_nulls(tweet.get('lang','')),
                'place_name':place_name,
                'geo':geo
            }
        res_tweets = connection.execute(sql_in_tweets,data)
         
        ########################################
        # insert into the tweet_urls table
        ########################################

        try:
            urls = tweet['extended_tweet']['entities']['urls']
        except KeyError:
            urls = tweet['entities']['urls']
        sql_in_tweet_urls=sqlalchemy.sql.text('''
        insert into tweet_urls
            (id_tweets, id_urls)
            values
            (:id_tweets, :id_urls)
            on conflict do nothing
            ;
        ''')
        id_tweet = tweet.get('id', None)
        for url in urls:
            id_urls = get_id_urls(url['expanded_url'], connection)
            
           # sql_in_tweet_urls=sqlalchemy.sql.text('''
            #    ''')
            res_insert_urls = connection.execute(sql_in_tweet_urls,
                    {'id_tweets':id_tweet, 'id_urls':id_urls})
        ########################################
        # insert into the tweet_mentions table
        ########################################

        try:
            mentions = tweet['extended_tweet']['entities']['user_mentions']
        except KeyError:
            mentions = tweet['entities']['user_mentions']
        for mention in mentions:
            # insert into users table;
            # note that we already have done an insert into the users table above for the user who sent a tweet;
            # that insert had lots of information inside of it (i.e. the user row was "hydrated");
            # when we only have a mention of a user, however, we do not have all the information to store in the row;
            # therefore, we must store the user info "unhydrated"
            # HINT:
            # use the ON CONFLICT DO NOTHING syntax
           #TODO: probably check if the user is already in the users table
           #one problem might be that we don't have access to uncommited changes
           # to users table above
            sql_id_users_insert=sqlalchemy.sql.text('''
                insert into users
                    (id_users, screen_name, name)
                    values
                    (:id_users, :screen_name, :name)
                on conflict do nothing
                ;
                ''')

            res_insert = connection.execute(sql_id_users_insert,
                    {'id_users':mention.get('id',None),
                     'screen_name':remove_nulls(mention.get('screen_name',None)),
                     'name':remove_nulls(mention.get('name',None)),
                    })

            # insert into tweet_mentions
            sql_into_tweet_mentions=sqlalchemy.sql.text('''
              insert into tweet_mentions
                  (id_tweets, id_users)
                  values
                  (:id_tweets, :id_users)
              on conflict do nothing
              ;
            ''')

            res_mention_insert = connection.execute(sql_into_tweet_mentions,
                    {'id_tweets':tweet.get('id',None), 'id_users':mention.get('id',None)})
        ########################################
        # insert into the tweet_tags table
        ########################################

        try:
            hashtags = tweet['extended_tweet']['entities']['hashtags'] 
            cashtags = tweet['extended_tweet']['entities']['symbols'] 
        except KeyError:
            hashtags = tweet['entities']['hashtags']
            cashtags = tweet['entities']['symbols']

        tags = [ '#'+hashtag['text'] for hashtag in hashtags ] + [ '$'+cashtag['text'] for cashtag in cashtags ]

        sql_into_tags=sqlalchemy.sql.text('''
             insert into tweet_tags
                (id_tweets, tag)
                values
                (:id_tweets, :tag)
             on conflict do nothing
             ;
         ''')

        for tag in tags: 
            res_tags_insert = connection.execute(sql_into_tags,
                    {'id_tweets':tweet.get('id',None), 'tag': remove_nulls(tag)}
                    )
        
        ########################################
        # insert into the tweet_media table
        ########################################

        try:
            media = tweet['extended_tweet']['extended_entities']['media']
        except KeyError:
            try:
                media = tweet['extended_entities']['media']
            except KeyError:
                media = []
        
        sql_into_media = sqlalchemy.sql.text('''
            insert into tweet_media
                (id_tweets, id_urls, type)
                values
                (:id_tweets, :id_urls, :type)
            on conflict do nothing
            ;
        ''')

        for medium in media:
            id_urls = get_id_urls(medium['media_url'], connection)
            
            res_media_insert = connection.execute(sql_into_media,
                   {'id_tweets':tweet.get('id',None), 'id_urls':id_urls,
                       'type':medium.get('type',None)}
                   )

################################################################################
# main functions
################################################################################

if __name__ == '__main__':
    
    # process command line args
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    parser.add_argument('--inputs',nargs='+',required=True)
    parser.add_argument('--print_every',type=int,default=1000)
    args = parser.parse_args()

    # create database connection
    engine = sqlalchemy.create_engine(args.db, connect_args={
        'application_name': 'load_tweets.py',
        })
    connection = engine.connect()

    # loop through the input file
    # NOTE:
    # we reverse sort the filenames because this results in fewer updates to the users table,
    # which prevents excessive dead tuples and autovacuums
    for filename in sorted(args.inputs, reverse=True):
        with zipfile.ZipFile(filename, 'r') as archive: 
            print(datetime.datetime.now(),filename)
            for subfilename in sorted(archive.namelist(), reverse=True):
                with io.TextIOWrapper(archive.open(subfilename)) as f:
                    for i,line in enumerate(f):

                        # load and insert the tweet
                        tweet = json.loads(line)
                        insert_tweet(connection,tweet)

                        # print message
                        if i%args.print_every==0:
                            print(datetime.datetime.now(),filename,subfilename,'i=',i,'id=',tweet['id'])
