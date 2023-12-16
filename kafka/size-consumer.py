import json
import os
from kafka import KafkaConsumer
import stldim
from main import storage
import psycopg2 as pg
from psycopg2 import pool
import requests

# Create the DB Connectionpool
threaded_postgreSQL_pool = pg.pool.ThreadedConnectionPool(1, 10, user=os.getenv('PG_USERNAME'),
                                                          password=os.getenv('PG_PASSWORD'),
                                                          host=os.getenv('PG_HOST'),
                                                          port=int(os.getenv('PG_PORT')) if os.getenv(
                                                              "PG_PORT") else 5432,
                                                          database=os.getenv('PG_DATABASE'))

consumer = KafkaConsumer(os.getenv("KAFKA_TOPIC"),
                         group_id=os.getenv("KAFKA_GROUP_ID"),
                         value_deserializer=lambda m: json.loads(m.decode('ascii')),
                         bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS").split(","))

conn = threaded_postgreSQL_pool.getconn()
cursor = conn.cursor()


def update_size_of_modell(id, file_path, file_name):
    storage.getFile(file_path, file_name)

    x, y, z = stldim.get_dimensions(file_name)

    cursor.execute("UPDATE item_files SET dim_x = %s, dim_y = %s, dim_z = %s WHERE file_path = %s",
                   (x.item(), y.item(), z.item(), file_path))
    conn.commit()

    os.remove("./" + file_name)

    rqst_path = os.getenv("CURA_DOMAIN") + "/hooks/calculate-print-size?file=" + file_path
    print(rqst_path, flush=True)
    requests.get(rqst_path)

    return {"id": id, "x": x.item(), "y": y.item(), "z": z.item()}


for message in consumer:
    print("%s:%d:%d: key=%s value=%s" % (message.topic, message.partition,
                                         message.offset, message.key,
                                         message.value))

    update_size_of_modell(message.value['item_file']['item_id'],
                          message.value['item_file']['file_path'],
                          message.value['item_file']['file_name'])
