import digitalocean
from minio import Minio
import os

PROVIDER_MINIO = "MINIO"
PROVIDER_DIGITALOCEAN = "DIGITALOCEAN"


class ItemifyStorage:
    def __init__(self, provider, **kwargs):
        self.provider = provider

        if provider == PROVIDER_MINIO:
            # Create a minio client
            self.client = Minio(
                os.getenv('MINIO_DOMAIN'),
                access_key=os.environ["MINIO_ACCESS_KEY"],
                secret_key=os.environ["MINIO_SECRET_KEY"],
                secure=True
            )
        elif provider == PROVIDER_DIGITALOCEAN:
            self.client = digitalocean.get_spaces_client(
                region_name=os.getenv('MINIO_DOMAIN').split(".")[0],
                endpoint_url=os.getenv('MINIO_DOMAIN'),
                key_id=os.environ["MINIO_ACCESS_KEY"],
                secret_access_key=os.environ["MINIO_SECRET_KEY"]
            )

    def getFile(self, file_path, file_name):
        if self.provider == PROVIDER_MINIO:
            self.client.fget_object(os.getenv('MINIO_BUCKET_NAME'), file_path, file_name)

        if self.provider == PROVIDER_DIGITALOCEAN:
            print(f"filepath: {file_path} file_name: {file_name}")
            digitalocean.get_file(self.client, os.getenv('MINIO_BUCKET_NAME'), file_path, file_name)

    def storeFile(self, filename, file):
        if self.provider == PROVIDER_MINIO:
            self.client.fput_object(os.getenv('MINIO_BUCKET_NAME'), filename, file.file.fileno())

        if self.provider == PROVIDER_DIGITALOCEAN:
            digitalocean.upload_file_to_space(self.client, os.getenv('MINIO_BUCKET_NAME'), file.file, filename, is_public=True)
