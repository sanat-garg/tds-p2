# Official Playwright Python image (includes Chromium, FF, WebKit)
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# Copy your code
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Start the API with gunicorn
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080", "--timeout", "200"]
