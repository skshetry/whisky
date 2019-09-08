from wsgi_app import application
from wsgi_server import WSGIRequestHandler, WSGIServer

if __name__ == "__main__":
    # create a simple WSGI server and run the application
    print("Running test application - point your browser at http://localhost:8000/ ...")
    httpd = WSGIServer(("", 8000), WSGIRequestHandler)
    httpd.set_app(application)
    httpd.serve_forever()
