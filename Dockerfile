FROM docker.io/library/python:3.13-slim-bookworm
ARG ERP_SOURCE_URL
LABEL org.opencontainers.image.source="${ERP_SOURCE_URL}"
WORKDIR /srv/erp
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --no-create-home erp
COPY app ./app
COPY web ./web
USER erp
EXPOSE 8080
CMD ["python", "app/main.py"]
