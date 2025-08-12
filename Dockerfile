# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app.py .
RUN mkdir -p avatars

# Expose port 8080 (Render default)
EXPOSE 8080

# Set environment variables for Flask (optional)
ENV FLASK_ENV=production
ENV PORT=8080

# Run the app with Gunicorn on port 8080, 1 worker
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app", "--workers", "1", "--timeout", "120"]
