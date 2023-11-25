import boto3
import mimetypes
import filetype
import os
import requests
import shutil

def get_spaces_client(**kwargs):
    """
    :param kwargs:
    :return:
    """
    region_name = kwargs.get("region_name")
    endpoint_url = kwargs.get("endpoint_url")
    key_id = kwargs.get("key_id")
    secret_access_key = kwargs.get("secret_access_key")

    session = boto3.session.Session()

    return session.client(
        's3',
        region_name=region_name,
        endpoint_url="https://" + endpoint_url,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret_access_key
    )

def get_file(spaces_client, bucket,  objectname, filename):
    print("Before Download: ")
    print(os.listdir("."))
    print(bucket, objectname, filename)
    
    url=f"https://{bucket}.fra1.digitaloceanspaces.com/{objectname}"
    response = requests.get(url, stream=True)
    with open(filename, 'wb') as data:
        shutil.copyfileobj(response.raw, data)
    
    print("After Download:")
    print(os.listdir("."))


def upload_file_to_space(spaces_client, space_name, file_src, save_as, **kwargs):
    """
    :param spaces_client: Your DigitalOcean Spaces client from get_spaces_client()
    :param space_name: Unique name of your space. Can be found at your digitalocean panel
    :param file_src: File on your disk
    :param save_as: Where to save your file in the space
    :param kwargs
    :return:
    """

    is_public = kwargs.get("is_public", False)
    meta = kwargs.get("meta")

    extra_args = {
        'ACL': "public-read" if is_public else "private"
    }

    if isinstance(meta, dict):
        extra_args["Metadata"] = meta

    return spaces_client.upload_fileobj(
        file_src,
        space_name,
        save_as,

        # boto3.s3.transfer.S3Transfer.ALLOWED_UPLOAD_ARGS
        ExtraArgs=extra_args
    )
