FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy every top-level Python module — main.py imports from greetings.py,
# and as students add more modules the glob picks them up automatically.
COPY *.py ./

# Schema migration SQL files. Applied by notes_dao.apply_migrations() on
# app startup — see the lifespan hook in main.py.
COPY migrations/ ./migrations/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
