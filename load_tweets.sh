#!/bin/sh

# list all of the files that will be loaded into the database
# for the first part of this assignment, we will only load a small test zip file with ~10000 tweets
# but we will write are code so that we can easily load an arbitrary number of files
files='
test-data.zip
'

echo 'load normalized'
for file in $files; do
    # call the load_tweets.py file to load data into pg_normalized
    continue
done

echo 'load denormalized'
for file in $files; do
    # use SQL's COPY command to load data into pg_denormalized
    #echo "$file"
    zcat $file | sed 's/\\u0000//g' | psql postgresql://postgres:pass@0.0.0.0:7500:5432/postgres  -c "COPY tweets_jsonb (data) FROM STDIN csv quote e'\x01' delimiter e'\x02';"
done
