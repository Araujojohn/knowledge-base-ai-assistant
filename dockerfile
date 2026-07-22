FROM python:3.13-slim-bookworm

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY . .

CMD uvicorn api:app --host 0.0.0.0