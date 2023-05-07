import json
import sys
import requests
import datetime
from kafka import KafkaProducer, KafkaConsumer

NEWS_API_ENDPOINT = 'https://newsapi.org/v2/everything'
newsapi_key = '470b0ff17b994482bf1f4eacb76d11eb'
#KAFKA_BROKER_ENDPOINT = 'localhost:9092'
KAFKA_BROKER_ENDPOINT = 'kafka.core:9092'
KAFKA_TOPIC = 'esg-news'

def consume_kafka_topic():
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKER_ENDPOINT,
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        auto_offset_reset='earliest'
    )

    for message in consumer:
        print("Message: ", message.value)

def main():
    with open('config.json', 'r') as config_file:
        config_data = json.load(config_file)

    keywords = config_data.get('keywords', '')

    if not keywords:
        print("Error: No keywords found in the config file.")
        sys.exit(1)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=15)

    # Fetch news articles using the News API
    response = requests.get(NEWS_API_ENDPOINT, params={
        'q': keywords,
        'from': yesterday.isoformat(),
        'apiKey': newsapi_key
    })

    print('Response object type: ', type(response.text), len(response.text))

    # Extract news articles from the response
    articles = response.json()['articles']

    # Create a Kafka producer instance
    producer = KafkaProducer(bootstrap_servers=KAFKA_BROKER_ENDPOINT)

    # Publish each news article to the Kafka topic
    for article in articles:
        article_json = json.dumps(article)
        producer.send(KAFKA_TOPIC, value=article_json.encode('utf-8'))

    # Close the Kafka producer
    producer.close()

    # Consume the Kafka topic messages
    consume_kafka_topic()

if __name__ == '__main__':
    main()
