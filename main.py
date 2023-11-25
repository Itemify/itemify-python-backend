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
import numpy
from stl import mesh
from mpl_toolkits import mplot3d
from matplotlib import pyplot
from matplotlib.colors import LightSource

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
        INSERT INTO item_files(item_id, file_name, file_type, file_path, license_name, render_image) 
            VALUES($1, $2, 'item', $3, (SELECT license_name FROM items WHERE item_id = $1), $4)
        ON CONFLICT DO NOTHING;
"""

SQL_EXEC_INSERT_IMAGE = "EXECUTE insert_image (%s, %s)"
SQL_EXEC_INSERT_ITEM = "EXECUTE insert_item (%s, %s, %s, %s)"
cursor.execute(SQL_PREP_INSERT_IMAGE)
cursor.execute(SQL_PREP_INSERT_ITEM)


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


def plotSTLToPNG(filename):
    # Create a new plot
    figure = pyplot.figure(figsize=(20,20))
    axes = figure.add_subplot(111, projection='3d')

    # Load the STL mesh
    stlmesh = mesh.Mesh.from_file(filename)
    polymesh = mplot3d.art3d.Poly3DCollection(stlmesh.vectors)

    # Create light source
    ls = LightSource(azdeg=225, altdeg=45)

    # Darkest shadowed surface, in rgba
    dk = numpy.array([66/255, 4/255, 126/255, 1])
    # Brightest lit surface, in rgba
    lt = numpy.array([7/255, 244/255, 158/255, 1])
    # Interpolate between the two, based on face normal
    shade = lambda s: (lt-dk) * s + dk

    # Set face colors 
    sns = ls.shade_normals(stlmesh.get_unit_normals(), fraction=1.0)
    rgba = numpy.array([shade(s) for s in sns])
    polymesh.set_facecolor(rgba)

    axes.add_collection3d(polymesh)

    # Adjust limits of axes to fill the mesh, but keep 1:1:1 aspect ratio
    pts = stlmesh.points.reshape(-1,3)
    ptp = max(numpy.ptp(pts, 0))/2
    ctrs = [(min(pts[:,i]) + max(pts[:,i]))/2 for i in range(3)]
    lims = [[ctrs[i] - ptp, ctrs[i] + ptp] for i in range(3)]
    axes.auto_scale_xyz(*lims)
    axes.set_axis_off()
    
    pyplot.savefig(filename + ".png", bbox_inches='tight')


@app.post("/files/")
async def create_file(file: UploadFile, is_image: bool = Form(...), model_id: int = Form(...), token=Depends(get_auth)):
    if is_image:
        filename = str(model_id) + "/img/" + file.filename
        cursor.execute(SQL_EXEC_INSERT_IMAGE, (model_id, filename))
        conn.commit()
        record = model_id

        storage.storeFile(filename, file)

    else:
        model_exist = model_id != -1

        if not model_exist:
            cursor.execute("SELECT nextval('items_item_id_seq');")
            record = cursor.fetchone()
            conn.commit()

            model_id = record[0]

        filename = str(model_id) + "/" + file.filename


        # generate a png of the model
        outPNG_Name = f"{model_id}_{file.filename}"

        with open(outPNG_Name, "wb+") as file_object:
            file_object.write(file.file.read())

        with open(outPNG_Name, "rb+") as file_object:
            storage.storeNormalFile(filename, file_object)

        plotSTLToPNG(outPNG_Name)

        with open(outPNG_Name + ".png", "rb+") as img:
            storage.storeNormalFile(str(model_id) + "/img/" + file.filename + ".png", img)

        if model_exist:
            cursor.execute(SQL_EXEC_INSERT_ITEM, (model_id, file.filename, filename, str(model_id) + "/img/" + file.filename + ".png"))
            conn.commit()

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
