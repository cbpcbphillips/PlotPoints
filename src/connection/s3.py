"""boto3 S3 client using the write-only uploader credentials."""

import os

import boto3
from dotenv import load_dotenv

from connection._env import require_env

load_dotenv()


def get_s3_client():
    """Return a boto3 S3 client using the write-only uploader credentials."""
    return boto3.client(
        "s3",
        aws_access_key_id=require_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=require_env("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION") or "us-east-1",
    )
