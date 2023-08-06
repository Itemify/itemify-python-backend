from fastapi.security import OAuth2AuthorizationCodeBearer
from keycloak import KeycloakOpenID  # pip require python-keycloak
from fastapi import Security, HTTPException, status, Depends
from pydantic import Json
import psycopg2 as pg
from psycopg2 import pool
import os 

server_url = "https://auth.baackfs.com/"
token_url = server_url + "/realms/application-sso/protocol/openid-connect/token"
auth_url = server_url + "/realms/application-sso/protocol/openid-connect/auth"
client_id = "itemify"

# Create the DB Connectionpool
threaded_postgreSQL_pool = pg.pool.ThreadedConnectionPool(2, 10, user=os.getenv('PG_USERNAME'),
                                                          password=os.getenv('PG_PASSWORD'),
                                                          host=os.getenv('PG_HOST'),
                                                          port="5432",
                                                          database=os.getenv('PG_DATABASE'))

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=server_url,  # https://sso.example.com/auth/
    tokenUrl=token_url,  # https://sso.example.com/auth/realms/example-realm/protocol/openid-connect/token
)

# This actually does the auth checks
keycloak_openid = KeycloakOpenID(
    server_url=server_url,  # https://sso.example.com/auth/
    client_id=client_id,  # backend-client-id
    realm_name="application-sso",  # example-realm
    verify=True
)


async def get_auth(token: str = Security(oauth2_scheme)) -> Json:
    try:
        KEYCLOAK_PUBLIC_KEY = (
            "-----BEGIN PUBLIC KEY-----\n"
            + keycloak_openid.public_key()
            + "\n-----END PUBLIC KEY-----"
        )
        
        decoded = keycloak_openid.decode_token(
            token,
            key=KEYCLOAK_PUBLIC_KEY,
            options={
                "verify_signature": True,
                "verify_aud": False,
                "exp": True
            }
        )

        conn = threaded_postgreSQL_pool.getconn()
        cursor = conn.cursor()
        
        sql = "INSERT INTO creators(creator_name, username, sub) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"

        cursor.execute(sql, (decoded["name"], decoded["preferred_username"], decoded["sub"] ))
        conn.commit()

        cursor.close()

        threaded_postgreSQL_pool.putconn(conn)

        print(decoded)

        return decoded

    except Exception as e:
        print(e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),  # "Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
