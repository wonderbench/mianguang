FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.txt
COPY . /app
RUN mkdir -p /app/staticfiles && chown 10001:10001 /app/staticfiles
USER 10001:10001
WORKDIR /app/app
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "30", "--error-logfile", "-"]
