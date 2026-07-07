FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py censor.py history.py modes.py media.py ./

CMD ["python", "bot.py"]
