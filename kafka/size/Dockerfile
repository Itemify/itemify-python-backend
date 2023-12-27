FROM python:3.9-slim

RUN apt update
RUN apt-get install -y libpq-dev gcc

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

# idk why, but without this its not working..
RUN pip3 uninstall -y python-keycloak
RUN pip3 install python-keycloak

COPY . .

CMD ["python3", "kafka/size/size-consumer.py"]
