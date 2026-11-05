import json
import logging
import socket
import time
from datetime import datetime, timezone

from flask import Flask, Response, g, request
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Histogram,
                               generate_latest)

APP_NAME = "mi-app-python"
PORT = 8000
LOGSTASH_HOST = "localhost"
LOGSTASH_PORT = 5001


class LogstashTCPHandler(logging.Handler):
    """Envía cada log como un JSON por línea a Logstash (TCP)."""

    def __init__(self, host, port, application):
        super().__init__()
        self.host = host
        self.port = port
        self.application = application
        self.sock = None

    def emit(self, record):
        try:
            ts = datetime.fromtimestamp(record.created, timezone.utc)
            payload = {
                "@timestamp": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "level": record.levelname,
                "message": record.getMessage(),
                "application": self.application,
                "logger_name": record.name,
                "thread_name": record.threadName,
            }
            data = (json.dumps(payload) + "\n").encode("utf-8")
            if self.sock is None:
                self.sock = socket.create_connection((self.host, self.port), timeout=2)
            self.sock.sendall(data)
        except Exception:
            # Si Logstash no responde, no tumbamos la app
            if self.sock is not None:
                try:
                    self.sock.close()
                except Exception:
                    pass
            self.sock = None


logger = logging.getLogger(APP_NAME)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())  # también en consola
logger.addHandler(LogstashTCPHandler(LOGSTASH_HOST, LOGSTASH_PORT, APP_NAME))

# Métricas
REQUESTS = Counter(
    "mi_app_http_requests_total",
    "Total de peticiones HTTP",
    ["method", "endpoint", "status"],
)
LATENCY = Histogram(
    "mi_app_http_request_duration_seconds",
    "Duración de las peticiones HTTP",
    ["endpoint"],
)

app = Flask(__name__)


@app.before_request
def start_timer():
    g.start = time.time()


@app.after_request
def record_metrics(response):
    endpoint = request.path
    REQUESTS.labels(request.method, endpoint, response.status_code).inc()
    LATENCY.labels(endpoint).observe(time.time() - g.start)
    return response


@app.route("/saludo")
def saludo():
    logger.info("Saludando desde mi app Python")
    return "Hola desde mi-app-python"


@app.route("/error")
def error():
    logger.error("Error simulado en mi app Python")
    return "Algo falló (simulado)", 500


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    logger.info("Iniciando %s en el puerto %s", APP_NAME, PORT)
    app.run(host="0.0.0.0", port=PORT)
