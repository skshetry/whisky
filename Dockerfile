FROM python:3.7.4-alpine3.10

WORKDIR /usr/src/app

COPY wsgi_app.py ./

COPY test_wsgi.py ./

CMD [ "python", "./test_wsgi.py" ]

COPY wsgi_server.py ./
