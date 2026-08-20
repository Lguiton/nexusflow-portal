# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for DuckDB and Qdrant
RUN apt-get update && apt-get install -y gcc g++ curl && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the actual backend code
COPY . /app/backend/

# Expose the API and WebSocket port
EXPOSE 8000

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Start the hardened Uvicorn server
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
