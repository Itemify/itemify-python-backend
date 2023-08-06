#!/bin/python3
import math

from fastapi import FastAPI, File, UploadFile, Form, Depends, Request
import os
from fastapi.middleware.cors import CORSMiddleware
import psycopg2 as pg
from psycopg2 import pool
import stripe
from pydantic import BaseModel
import stldim
import urllib.parse
import requests
from auth import get_auth
import itemifystorage as istore

# This is your test secret API key.
stripe.api_key = os.getenv('STRIPE_API_KEY')

# Setup the Server
app = FastAPI(
    swagger_ui_init_oauth={
        # If you are using pkce (which you should be)
        "usePkceWithAuthorizationCodeGrant": True,
        # Auth fill client ID for the docs with the below value
        "clientId": "itemify"  # example-frontend-client-id-for-dev
    }
)

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print(os.getenv('MINIO_DOMAIN'))

# Create a storage instance
storage = istore.ItemifyStorage(istore.PROVIDER_DIGITALOCEAN)

# Create the DB Connectionpool
threaded_postgreSQL_pool = pg.pool.ThreadedConnectionPool(2, 10, user=os.getenv('PG_USERNAME'),
                                                          password=os.getenv('PG_PASSWORD'),
                                                          host=os.getenv('PG_HOST'),
                                                          port="5432",
                                                          database=os.getenv('PG_DATABASE'))

conn = threaded_postgreSQL_pool.getconn()
cursor = conn.cursor()

SQL_PREP_INSERT_IMAGE = """
    PREPARE insert_image (int, text) AS
        INSERT INTO item_images VALUES($1, $2)
        ON CONFLICT DO NOTHING
"""

SQL_PREP_INSERT_ITEM = """
    PREPARE insert_item (int, text, text) AS
        INSERT INTO item_files(item_id, file_name, file_type, file_path, license_name) 
            VALUES($1, $2, 'item', $3, (SELECT license_name FROM items WHERE item_id = $1))
        ON CONFLICT DO NOTHING;
"""

SQL_EXEC_INSERT_IMAGE = "EXECUTE insert_image (%s, %s)"
SQL_EXEC_INSERT_ITEM = "EXECUTE insert_item (%s, %s, %s)"
cursor.execute(SQL_PREP_INSERT_IMAGE)
cursor.execute(SQL_PREP_INSERT_ITEM)


def update_size_of_modell(id, file_path, file_name):
    storage.getFile(file_path, file_name)

    x, y, z = stldim.get_dimensions(file_name)

    cursor.execute("UPDATE item_files SET dim_x = %s, dim_y = %s, dim_z = %s WHERE file_path = %s",
                   (x.item(), y.item(), z.item(), file_path))
    conn.commit()

    os.remove("./" + file_name)

    rqst_path = os.getenv("CURA_DOMAIN") + "/hooks/calculate-print-size?file=" + urllib.parse.quote(file_path)

    requests.get(rqst_path)

    return {"id": id, "x": x.item(), "y": y.item(), "z": z.item()}


@app.post("/files/")
async def create_file(file: UploadFile, is_image: bool = Form(...), model_id: int = Form(...), token=Depends(get_auth)):
    print(token)

    if is_image:
        filename = str(model_id) + "/img/" + file.filename
        cursor.execute(SQL_EXEC_INSERT_IMAGE, (model_id, filename))
        conn.commit()
        record = model_id
    else:
        model_exist = model_id != -1

        if not model_exist:
            cursor.execute("SELECT nextval('items_item_id_seq');")
            record = cursor.fetchone()
            conn.commit()

            model_id = record[0]

        filename = str(model_id) + "/" + file.filename

        if model_exist:
            cursor.execute(SQL_EXEC_INSERT_ITEM, (model_id, file.filename, filename))
            conn.commit()

    print(filename, flush=True)
    storage.storeFile(filename, file)

    if not is_image and model_exist:
        update_size_of_modell(model_id, filename, file.filename)

    return {"status": "200", "filename": filename, "recordId": model_id}


# @app.post("/item/update")
# async def create_file(file: UploadFile, is_image: bool = Form(...), model_id: int = Form(...), token=Depends(get_auth)):


class Order(BaseModel):
    delivery_id: int


class Item(BaseModel):
    id: int
    file_name: str
    file_path: str


def calculate_order_amount(items: Order):
    conn = threaded_postgreSQL_pool.getconn()
    cursor = conn.cursor()

    sql2 = """
        SELECT 
            SUM(
                3 * f.filament_used * q.quantity * 
                (SELECT material_price_per_gram FROM materials m WHERE material_name = a.material) 
                + 
                (SELECT material_price_per_print FROM materials m WHERE material_name = a.material) *
                q.quantity
            ) price,
            SUM(f.license_price * CASE WHEN f.is_license_applied_once THEN 1 ELSE q.quantity END) license_cost,
            AVG(c.shipping_cost) shipping_cost
        FROM delivery_item_quantity q 
        JOIN delivery_address a 
            ON q.delivery_id = a.delivery_id 
        JOIN item_files f 
            on f.item_id = q.item_id and f.file_name = q.file_name
        JOIN countries c
            on c.country_name = a.country
        WHERE q.delivery_id = %s
        GROUP BY a.country;
    """

    cursor.execute(sql2, (items.delivery_id,))
    data = cursor.fetchone()
    price = round(data[0])
    license_cost = data[1]
    shipping_cost = int(data[2])

    sql3 = """
    UPDATE delivery_address a SET price = %s WHERE a.delivery_id = %s; 
    UPDATE delivery_item_quantity q
        SET price = (
            SELECT 
                m.material_price_per_print * q.quantity + 
                m.material_price_per_gram * 3 * f.filament_used * q.quantity 
            FROM item_files f 
            JOIN filaments fila 
                ON q.filament_id = fila.filament_id
            JOIN materials m 
                ON m.material_name = fila.material
            WHERE f.item_id = q.item_id AND f.file_name = q.file_name
        ) 
    WHERE q.delivery_id = %s;
        
    """
    cursor.execute(sql3, (price + license_cost, items.delivery_id, items.delivery_id))
    conn.commit()

    threaded_postgreSQL_pool.putconn(conn)

    return (price, license_cost, shipping_cost)


@app.post('/calculate-size')
def calculate_size(item: Item, token=Depends(get_auth)):
    return update_size_of_modell(item.id, item.file_path, item.file_name)


@app.post('/update-views/{item_id}')
def update_views(item_id: int):
    conn = threaded_postgreSQL_pool.getconn()
    cursor = conn.cursor()

    sql = """
        UPDATE items SET views = views + 1 WHERE item_id = %s;
        INSERT INTO item_actions(item_id, action, value) VALUES(%s, %s, %s);
    """
    cursor.execute(sql, (item_id, item_id, "view", 1))
    conn.commit()

    threaded_postgreSQL_pool.putconn(conn)

    return {"status": 200}


@app.post('/create-payment-intent')
def create_payment(item: Order):
    price, license_cost, shipping_cost = calculate_order_amount(item)
    intent = stripe.PaymentIntent.create(
        amount=price + shipping_cost + license_cost,
        currency='eur',
        automatic_payment_methods={
            'enabled': True,
        },
        metadata={
            'delivery_id': item.delivery_id,
        }

    )

    return {"clientSecret": intent['client_secret'], "price": price, "shipping_cost": shipping_cost, "license_cost": license_cost}


@app.post("/stripe/hook")
async def stripeHook(request: Request):
    conn = threaded_postgreSQL_pool.getconn()
    cursor = conn.cursor()

    sql = "UPDATE delivery_address SET is_paid = 't' WHERE delivery_id = %s;"

    body = await request.json()

    amount = body["data"]["object"]["amount"]
    delivery_id = body["data"]["object"]["metadata"]["delivery_id"]

    cursor.execute(sql, (delivery_id,))
    conn.commit()

    threaded_postgreSQL_pool.putconn(conn)

    print("Delivery with id: {id} of {amount} got paid".format(id=delivery_id, amount=amount))

    return {"status": "succedded"}
