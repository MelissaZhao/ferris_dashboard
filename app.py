from flask import Flask, jsonify, render_template, request
import json
from kafka import KafkaConsumer
import os
import time
import logging
import colorsys
from minio import Minio
from minio.error import S3Error
from flask import send_from_directory
from flask import url_for
import random
import io 
import asyncio
from datetime import datetime, timedelta
import pytz


def generate_color():
    r = lambda: random.randint(0, 255)
    return '#{:02x}{:02x}{:02x}'.format(r(), r(), r())



logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

print("Templates folder path:", os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'))

app = Flask(__name__)

is_running = True


distinct_colors = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5", "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
    "#393b79", "#8ca252", "#d6616b", "#7b4173", "#b5cf6b", "#ce6dbd", "#bd9e39", "#e7969c", "#e7ba52", "#31a354"
]

# Configure MinIO client
minioClient = Minio(
    "minio.ferris.ai",
    access_key="demo",
    secret_key="ferrisdemo123",
    secure=True
)
@app.route('/api/json_file_url', methods=['GET'])
def get_json_file_url():
    chart_type = request.args.get('chart_type')
    json_file_name = f"{chart_type}_chart.json"
    json_file_url = minioClient.presigned_get_object('ferris-dash', json_file_name)
    return jsonify(url=json_file_url)

@app.route('/api/data', methods=['GET'])
def get_data():
    logger.info('inside api/data')
    chart_type = request.args.get('chart_type', default='pie', type=str)
    data = fetch_data_from_kafka(chart_type)
    return jsonify(data)

def fetch_data_from_kafka(chart_type):

    data = {
        'source_names': [],
        'counts': [],
        'count_time': [],
        'data': [],
        'title': f'ESG_News_Screen_{chart_type.capitalize()}_Chart',
        'type': chart_type
    }


    # Get the datetime 7 days ago in UTC timezone
    start_time = datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(days=7)
    # Format the start time string in the format expected by the Kafka message
    start_time_str = start_time.strftime('%Y-%m-%d')


    time.sleep(1)
    global is_running
    consumer = KafkaConsumer(
        'esg-news',
        #bootstrap_servers='localhost:9092',
        bootstrap_servers='kafka.core',
        value_deserializer=lambda x: json.loads(x.decode('utf-8')),
        auto_offset_reset='earliest',  # Start reading from the beginning of the topic
        consumer_timeout_ms=10000 # stop listening after 10s, otherwise loop doesn't exit
    )

    source_data = {}
    events_list = []

    for message in consumer:
        try:
            event = message.value
        except ValueError:
            logger.info(f"Invalid JSON message received: {message.value}")
            continue

        logger.info(f"Event received: {event}")

        source_name = event['source']['name']

        if source_name not in source_data:
            source_data[source_name] = 0

        source_data[source_name] += 1
        # Add the event to events_list
        events_list.append(event)

    consumer.close()

    if chart_type == 'pie':
        data['data'] = {
            "datasets": [{
                "backgroundColor": [],
                "data": [],
                "hoverOffset": 10
            }],
            "labels": []
        }

        for source_name, count in source_data.items():
            data['data']['labels'].append(source_name)
            data['data']['datasets'][0]['data'].append(count)
            data['data']['datasets'][0]['backgroundColor'].append(generate_color())

        data['title'] = "ESG_News_Screen_Pie_Chart"
        data['type'] = "pie"

    elif chart_type == 'line':
        labels = []
        for i in range(7):
            date = (datetime.now() - timedelta(days=6-i)).strftime('%Y-%m-%d')
            labels.append(date)
        data['data'] = {
            "datasets": [],
            "labels": labels
        }
        data['options'] = {
            "scales": {
                "y": {
                    "ticks": {
                        "callback": "function(value, index, values) { if (Number.isInteger(value)) { return value; }}",
                        }
                    }
                }
            }

        daily_source_counts = {source: {date: 0 for date in labels} for source in source_data.keys()}

        for item in events_list:
            published_time_str = item['publishedAt']
            published_time = datetime.fromisoformat(published_time_str).replace(tzinfo=pytz.utc)
            published_date_str = published_time.strftime('%Y-%m-%d')

            if published_date_str in labels:
                source_name = item['source']['name']
                daily_source_counts[source_name][published_date_str] += 1

        for i, (source_name, daily_counts) in enumerate(daily_source_counts.items()):
            color = distinct_colors[i % len(distinct_colors)]
            dataset = {
                "backgroundColor": color,
                "borderColor": color,
                "data": [int(daily_counts[date]) for date in labels],
                "fill": True,
                "label": source_name
            }
            data['data']['datasets'].append(dataset)

        data['title'] = "ESG_News_Screen_Line_Chart"
        data['type'] = "line"

    elif chart_type == 'table':
        source_counts = {}  # A dictionary to store the count of each source_name

        for item in events_list:
            # Parse the published time from the Kafka message
            published_time_str = item['publishedAt']
            published_time = datetime.fromisoformat(published_time_str).replace(tzinfo=pytz.utc)
            published_time_str = published_time.strftime('%Y-%m-%d')
            # Filter out data outside of the desired time range
            if published_time >= start_time:
                source_name = item['source']['name']

                if source_name in source_counts:
                    source_counts[source_name]['count'] += 1
                    if published_time > datetime.fromisoformat(source_counts[source_name]['count_time_stamp']).replace(tzinfo=pytz.utc):
                        source_counts[source_name]['count_time_stamp'] = published_time_str
                else:
                    source_counts[source_name] = {
                        'count': 1,
                        'count_time_stamp': published_time_str
                    }


        data['columns'] = [
            {
                "field": "source_name",
                "title": "Source Name"
            },
            {
                "field": "count",
                "title": "Total Published Last Week"
            },
            {
                "field": "count_time_stamp",
                "title": "Latest Publish Time"
            }
        ]
        data['data'] = []

        for source_name, source_data in source_counts.items():
            data['source_names'].append(source_name)
            data['counts'].append(source_data['count'])
            data['count_time'].append(source_data['count_time_stamp'])
            for dataset in data['data']:
                if dataset['source_name'] == source_name:
                    dataset['count'] = source_data['count']
                    break
            else:
                new_dataset = {
                    'source_name': source_name,
                    'count': source_data['count'],
                    'count_time_stamp': source_data['count_time_stamp']
                }
                data['data'].append(new_dataset)

    # ... (rest of the code remains the same)

    return data

    
def upload_to_minio(chart_type):
    # Fetch data from Kafka
    data = fetch_data_from_kafka(chart_type)

    if not data:
        logger.error(f"Failed to fetch data for {chart_type} chart")
        return

    if chart_type == 'pie':
        if data['data']['datasets']:
            background_color = data['data']['datasets'][0]['backgroundColor']
        else:
            background_color = "some_default_color"  # Use a default color if datasets is empty

        data_to_upload = {
            "title": "Esg_event",
            "type": "pie",
            "data": {
                "datasets": [{
                    "backgroundColor": data['data']['datasets'][0]['backgroundColor'],
                    "data": data['data']['datasets'][0]['data'],
                    "hoverOffset": 10
                }],
                "labels": data['data']['labels']
            }
        }
    elif chart_type == 'line':
        data_to_upload = {
            "title": "",
            "type": "line",
            "data": {
                "datasets": data['data']['datasets'],
                "labels": data['data']['labels']
            }
        }
    elif chart_type == 'table':
        data_to_upload = {
            "title":  "ESG_News_Screen_Table_Chart",
            "type": "table",
            "columns": data['columns'],
            "data": data['data']
        }

    # Convert the data object to a bytes stream
    bytes_stream = io.BytesIO(json.dumps(data).encode('utf-8'))

    file_name = f"{chart_type}_chart.json"

    try:
        minioClient.put_object("ferris-dash", file_name, bytes_stream, length=bytes_stream.getbuffer().nbytes)
        print(f"JSON file {file_name} uploaded to MinIO.")
    except S3Error as exc:
        print(f"Error uploading JSON file {file_name} to MinIO: {exc}")

def get_minio_url(chart_type):
    file_name = f"{chart_type}_chart.json"
    try:
        url = minioClient.presigned_get_object("ferris-dash", file_name)
        print(f"URL for {file_name}: {url}")
        return url
    except S3Error as exc:
        print(f"Error generating URL for {file_name}: {exc}")


upload_to_minio("pie")
url = get_minio_url("pie")

upload_to_minio("line")
url = get_minio_url("line")

upload_to_minio("table")
url = get_minio_url("table")

@app.route('/json_files/<path:filename>', methods=['GET'])
def serve_json_file(filename):
    return send_from_directory(directory="json_files", filename=filename)


@app.route('/')
def index():
    logger.info('inside index')
    json_file_url = url_for('serve_json_file', filename='<your_json_file_name>')
    return render_template('dashboard.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
