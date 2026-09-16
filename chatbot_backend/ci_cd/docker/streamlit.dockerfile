FROM python:3.10-slim

WORKDIR /app

COPY services/v1/streamlit_app/requirements.txt .
RUN pip install -r requirements.txt

COPY services/v1/streamlit_app .

EXPOSE 8501

CMD ["streamlit", "run", "app.py"]