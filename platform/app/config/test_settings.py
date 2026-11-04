import os

os.environ.setdefault("DJANGO_SECRET_KEY", "local-integration-tests-only-not-a-production-secret")
os.environ["DJANGO_DEBUG"] = "true"
from .settings import *  # noqa: F403

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
