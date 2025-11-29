FROM mcr.microsoft.com/playwright/python:v1.56.0

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080", "--timeout", "300"]
