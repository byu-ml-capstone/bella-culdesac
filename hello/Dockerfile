FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application modules. As the service grows, modules remain beside
# main.py so the container image stays self-contained.
COPY *.py ./

# Schema migration SQL files. Applied by the application migration runner
# during startup.
COPY migrations/ ./migrations/
COPY tests/ ./tests/
COPY static/ ./static/

RUN mkdir -p /app/storage/attachments

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
