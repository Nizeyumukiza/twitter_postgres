\set ON_ERROR_STOP on

--drop all tables
--drop table tweets_jsonb cascade;

BEGIN;

--------------------------------------------------------------------------------    
-- data tables
--------------------------------------------------------------------------------    

CREATE TABLE tweets_jsonb (
    data JSONB
);

--------------------------------------------------------------------------------    
-- the views below represent normalized tables
--------------------------------------------------------------------------------    

CREATE VIEW tweets AS (
    SELECT 
        data->>'id' AS id_tweets, 
        data->'user'->>'id' AS id_users,
        (data->>'created_at') :: TIMESTAMPTZ AS created_at,
        data->>'in_reply_to_status_id' AS in_reply_to_status_id,
        data->>'in_reply_to_user_id' AS in_reply_to_user_id,
        data->>'quoted_status_id' AS quoted_status_id,
        'FIXME' AS geo_coords, -- these "FIXME" columns involve complex python processing; they could be implemented in pure SQL, but it'd be a pain
        'FIXME' AS geo_string,
        data->>'retweet_count' AS retweet_count,
        data->>'quote_count' AS quote_count,
        data->>'favorite_count' AS favorite_count,
        data->>'withheld_copyright' AS withheld_copyright,
        data->'withheld_in_countries' AS withheld_in_countries,
        data->'place'->>'full_name' AS place_name,
        lower(data->'place'->>'country_code') AS country_code,
        'FIXME' AS state_code,
        data->>'lang' AS lang,
        COALESCE(data->'extended_tweet'->>'full_text',data->>'text') AS text,
        data->>'source' AS source
    FROM tweets_jsonb
);

CREATE VIEW tweet_mentions AS (
    SELECT DISTINCT id_tweets, jsonb->>'id' AS id_users
    FROM (
        SELECT
            data->>'id' AS id_tweets,
            jsonb_array_elements(
                COALESCE(data->'entities'->'user_mentions','[]') ||
                COALESCE(data->'extended_tweet'->'entities'->'user_mentions','[]')
            ) AS jsonb
        FROM tweets_jsonb
    ) t
);


CREATE VIEW tweet_tags AS (
    SELECT DISTINCT id_tweets, '$' || (jsonb->>'text'::TEXT) AS tag
    FROM (
        SELECT
            data->>'id' AS id_tweets,
            jsonb_array_elements(
                COALESCE(data->'entities'->'symbols','[]') ||
                COALESCE(data->'extended_tweet'->'entities'->'symbols','[]')
            ) AS jsonb
        FROM tweets_jsonb
    ) t
    UNION ALL
    SELECT DISTINCT id_tweets, '#' || (jsonb->>'text'::TEXT) AS tag
    FROM (
        SELECT
            data->>'id' AS id_tweets,
            jsonb_array_elements(
                COALESCE(data->'entities'->'hashtags','[]') ||
                COALESCE(data->'extended_tweet'->'entities'->'hashtags','[]')
            ) AS jsonb
        FROM tweets_jsonb
    ) t
);


CREATE VIEW tweet_media AS (
    SELECT DISTINCT
        id_tweets,
        jsonb->>'media_url' AS media_url,
        jsonb->>'type' AS type
    FROM (
        SELECT
            data->>'id' AS id_tweets,
            jsonb_array_elements(
                COALESCE(data->'extended_entities'->'media','[]') ||
                COALESCE(data->'extended_tweet'->'extended_entities'->'media','[]')
            ) AS jsonb
        FROM tweets_jsonb
    ) t
);



/*
 * Precomputes the total number of occurrences for each hashtag
 */
CREATE VIEW tweet_tags_total AS (
    SELECT 
        row_number() over (order by count(*) desc) AS row,
        tag, 
        count(*) AS total
    FROM tweet_tags
    GROUP BY tag
    ORDER BY total DESC
);

/*
 * Precomputes the number of hashtags that co-occur with each other
 */
CREATE VIEW tweet_tags_cooccurrence AS (
    SELECT 
        t1.tag AS tag1,
        t2.tag AS tag2,
        count(*) AS total
    FROM tweet_tags t1
    INNER JOIN tweet_tags t2 ON t1.id_tweets = t2.id_tweets
    GROUP BY t1.tag, t2.tag
    ORDER BY total DESC
);


COMMIT;
