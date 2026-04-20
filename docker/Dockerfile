FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install only Chromium (scraper uses chromium.launch() exclusively)
# Firefox + WebKit would add ~500MB with no functional benefit.
RUN playwright install chromium

COPY . .

EXPOSE 8000

CMD ["python", "-m", "app.run"]
