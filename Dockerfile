FROM python:3.12-slim
WORKDIR /app
# Логи сразу видны на сервере, а не пачками
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
