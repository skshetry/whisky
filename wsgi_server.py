#! /usr/bin/env python3
import argparse
import collections.abc
import concurrent.futures
import datetime
import importlib
import io
import logging
import selectors
import socket
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
DEFAULT_PORT = 8000
DEFAULT_WORKERS = 4


class WSGIRequestHandler:
    def __init__(self, request, client_address, server):
        self.client_address = client_address
        self.server = server
        self.request = request

        app = server.get_app()
        if not isinstance(app, collections.abc.Callable):
            raise TypeError(
                "The wsgi app specified %s is not a valid WSGI application.", str(app)
            )

        self.handle(request, app)

    def get_environ(self):
        env = self.server.get_environ().copy()
        env["REQUEST_METHOD"] = self.method
        env["SERVER_PROTOCOL"] = self.http_version
        env["wsgi.input"] = io.StringIO(self.data)

        if "?" in self.path:
            env["PATH_INFO"], env["QUERY_STRING"] = self.path.split("?", 1)
        else:
            env["PATH_INFO"] = self.path

        for key, value in self.headers:
            key: str = key
            env[str("HTTP_" + key.replace("-", "_").upper())] = value

        if "HTTP_CONTENT_LENGTH" in env:
            env["CONTENT_LENGTH"] = env["HTTP_CONTENT_LENGTH"]

        if "HTTP_CONTENT_TYPE" in env:
            env["CONTENT_TYPE"] = env["HTTP_CONTENT_TYPE"]

        return env

    def handle(self, request, application):
        req_data = request.recv(1024)

        self.data = req_data.decode("utf-8")
        self.method, self.path, self.http_version = self.parse_request(self.data)
        self.headers = self.parse_headers(self.data)

        logger.debug("".join(f"< {line}\n" for line in req_data.splitlines()))

        env = self.get_environ()

        if env.get("HTTP_EXPECT", "") == "100-continue":
            res = env["SERVER_PROTOCOL"] + " 100 Continue\r\n\r\n"
            request.sendall(res.encode())

        result = application(env, self.start_response)
        self.finish_response(result, request)

        logger.info(
            '%s [%s] "%s %s %s" %s -',
            self.client_address[0],
            self.datetime,
            self.method,
            self.path,
            self.http_version,
            self.status,
        )

    def parse_request(self, req):
        request_line = req.splitlines()[0]
        return request_line.rstrip("\r\n").split()

    def parse_headers(self, req):
        # only get headers in format "Key: Value", also removes GET /index HTTP/1.1
        raw_headers = filter(lambda line: ":" in line, req.splitlines())

        return (
            # remove whitespaces and split based on ":" (colon)
            header.strip().replace(" ", "").split(":", 1)
            for header in raw_headers
        )

    def start_response(self, status, response_headers, exc_info=None):
        self.datetime = datetime.datetime.now(tz=datetime.timezone.utc).strftime(
            "%a, %d %b %Y %T.%f %Z"
        )

        server_headers = [("Date", self.datetime), ("Server", "WSGIServer 0.2")]
        self.headers_set = [status, response_headers + server_headers]

        return lambda data: logger.warning(
            "Please do not use write() function.\n %s", data
        )

    def finish_response(self, result, request):
        self.status, response_headers = self.headers_set
        response = f"HTTP/1.1 {self.status}\r\n"
        for header in response_headers:
            response += "{0}: {1}\r\n".format(*header)
        response += "\r\n"
        for data in result:
            response += data.decode("utf-8")
        logger.debug("".join(f"> {line}\n" for line in response.splitlines()))
        response_bytes = response.encode()
        request.sendall(response_bytes)


class WSGIServer:
    address_family = socket.AF_INET
    socket_type = socket.SOCK_STREAM
    request_queue_size = 20

    def _create_listening_socket(self, server_address):
        listening_socket = socket.socket(self.address_family, self.socket_type)
        listening_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listening_socket.bind(server_address)
        listening_socket.setblocking(False)
        listening_socket.listen(self.request_queue_size)
        return listening_socket

    def __init__(self, server_address, request_handler_class, max_workers=4):
        self.request_handler_class = request_handler_class

        self.listening_socket = self._create_listening_socket(server_address)
        host, self.server_port, *_ = self.listening_socket.getsockname()
        self.server_name = socket.getfqdn(host)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._selector = selectors.DefaultSelector()
        self._application = None

    def get_app(self):
        return self._application

    def set_app(self, application):
        self._application = application

    def serve_forever(self):
        self._selector.register(
            self.listening_socket, selectors.EVENT_READ, self.handle_request
        )

        while True:
            for key, mask in self._selector.select(timeout=1):
                callback = key.data
                callback(key.fileobj, mask)

    def get_environ(self):
        env = {}
        env["wsgi.version"] = (1, 0)

        env["wsgi.url_scheme"] = "http"
        env["wsgi.errors"] = sys.stderr

        if self.executor._max_workers == 1:
            multithreaded = False
        else:
            multithreaded = True
        env["wsgi.multithread"] = multithreaded

        env["wsgi.multiprocess"] = False
        env["wsgi.run_once"] = False
        # Required CGI variables
        env["SERVER_NAME"] = self.server_name
        env["SERVER_PORT"] = str(self.server_port)
        env["SCRIPT_NAME"] = ""
        env["SERVER_SOFTWARE"] = ""

        return env

    def process_request_thread(self, client_conn, client_address):
        self.finish_request(client_conn, client_address)
        self.shutdown_request(client_conn)

    def process_request(self, client_conn, mask, client_address):
        self.executor.submit(self.process_request_thread, client_conn, client_address)

    def finish_request(self, client_conn, client_address):
        self.request_handler_class(client_conn, client_address, self)

    def shutdown_request(self, client_conn):
        self.close_request(client_conn)

    def close_request(self, client_conn: socket.socket):
        self._selector.unregister(client_conn)
        client_conn.close()

    def handle_request(self, sock, mask):
        client_socket, client_address = self.listening_socket.accept()
        client_socket.settimeout(200)
        client_socket.setblocking(False)
        self._selector.register(
            client_socket,
            selectors.EVENT_READ,
            lambda sock, mask: self.process_request(sock, mask, client_address),
        )

    def close_server(self):
        self._selector.unregister(self.listening_socket)
        self._selector.close()
        self.executor.shutdown(wait=True)
        self.listening_socket.close()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close_server()

    def __enter__(self):
        return self


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "application",
        help="wsgi application in the form module:callable, eg: wsgi_app:application",
    )
    parser.add_argument("-d", "--debug", help="Enable debug mode", action="store_true")
    parser.add_argument(
        "-b", "--bind", help="Specify alternate bind address", default=""
    )
    parser.add_argument(
        "-p",
        "--port",
        help="Specify alternate port [default: {0}]".format(DEFAULT_PORT),
        default=DEFAULT_PORT,
        type=int,
    )
    parser.add_argument(
        "--workers",
        help="No. of threads to handle requests",
        default=DEFAULT_WORKERS,
        type=int,
    )

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    app_path = args.application
    module, application = app_path.split(":")

    module = importlib.import_module(module)
    application = getattr(module, application)

    httpd = WSGIServer(
        (args.bind, args.port), WSGIRequestHandler, max_workers=args.workers
    )
    httpd.set_app(application)

    logger.info("Serving on Port %s ...", args.port)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()  # print log on next line of ^C
        logger.warning("Closing server ...")
        httpd.close_server()
