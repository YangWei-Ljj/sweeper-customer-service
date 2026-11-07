FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python scripts/init_db.py

EXPOSE 8513
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.port", "8513", "--server.address", "0.0.0.0", "--server.headless", "true"]
