FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
ENV DATABASE_URL=sqlite:////data/swarm.db
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
