FROM python:3.12-slim
WORKDIR /app
COPY master/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY master /app/master
CMD ["python", "-m", "master"]
