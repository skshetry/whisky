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
from collections import OrderedDict
from http import HTTPStatus

__version__ = "0.1.1"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
DEFAULT_PORT = 8000
DEFAULT_WORKERS = 4
CRLF = "\r\n"

acceptable_encodings = ["gzip", "identity"]
iana_registered_encodings = ["gzip", "compress", "deflate", "identity", "br"]


class HttpRequestParseError(Exception):
    pass


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
        self.handle(app)

    def get_environ(self):
        env = self.server.get_environ().copy()
        env["REQUEST_METHOD"] = self.method.upper()
        env["SERVER_PROTOCOL"] = self.http_version
        env["wsgi.input"] = io.BytesIO(self.data)

        if "?" in self.path:
            env["PATH_INFO"], env["QUERY_STRING"] = self.path.split("?", 1)
        else:
            env["PATH_INFO"] = self.path

        for key, value in self.headers.items():
            env[str("HTTP_" + key.replace("-", "_").upper())] = value

        if "HTTP_CONTENT_LENGTH" in env:
            env["CONTENT_LENGTH"] = env["HTTP_CONTENT_LENGTH"]

        if "HTTP_CONTENT_TYPE" in env:
            env["CONTENT_TYPE"] = env["HTTP_CONTENT_TYPE"]

        return env

    def send_error(self, code):
        status = HTTPStatus(value=code)
        self.request.sendall(b"HTTP/1.1 {status.value} {status.name}\r\n")

    def handle(self, application):
        req_data = self.request.recv(1024)

        if not req_data:
            return

        raw_data = req_data

        self.parse_request(raw_data)

        logger.debug("".join(f"< {line}\n" for line in req_data.splitlines()))

        env = self.get_environ()

        if env.get("HTTP_EXPECT", "") == "100-continue":
            res = env["SERVER_PROTOCOL"] + " 100 Continue\r\n\r\n"
            self.request.sendall(res.encode())

        try:
            self.parsed_encodings = self.parse_encodings(
                env.get("HTTP_ACCEPT_ENCODING", "")
            )
            is_acceptable = any(
                [encoding in self.parsed_encodings for encoding in acceptable_encodings]
            )
            if not is_acceptable:
                logger.debug(
                    "None of the encodings are supported out of: %s",
                    self.parsed_encodings,
                )
                self.send_error(code=HTTPStatus.NOT_ACCEPTABLE)
                return
        except HttpRequestParseError as exc:
            logger.debug("Could not accept encoding: Reason: %s", str(exc))
            self.send_error(code=HTTPStatus.NOT_ACCEPTABLE)
            return

        if env.get("CONTENT_LENGTH"):
            size = int(env.get("CONTENT_LENGTH", "0")) - len(self.data)
            parts = [1024] * (size // 1024) + [size % 1024]

            # size % 1024 might be zero, remove if it is
            parts = parts[:-1] if parts[-1] == 0 else parts

            logger.debug("Receiving data of size {0} in parts {1}".format(size, parts))

            for part in parts:
                packet = self.request.recv(part)
                if not packet:
                    break
                env["wsgi.input"].write(packet)
            env["wsgi.input"].seek(0)

        result = application(env, self.start_response)
        self.finish_response(result)

        logger.info(
            '%s [%s] "%s %s %s" %s -',
            self.client_address[0],
            self.datetime,
            self.method,
            self.path,
            self.http_version,
            self.status,
        )

    @staticmethod
    def parse_encodings(encodings: str):
        """
        Accept-Encoding: compress, gzip
        Accept-Encoding:
        Accept-Encoding: *
        Accept-Encoding: compress;q=0.5, gzip;q=1.0
        Accept-Encoding: gzip;q=1.0, identity; q=0.5, *;q=0
        """
        if encodings.strip().replace(" ", "") == "":
            return ["identity"]

        def parse_encoding(encoding):
            value = 0.01
            encoding = encoding.strip().replace(" ", "")
            if ";q=" in encoding:
                enc, _, value = encoding.partition(";q=")
                if not enc or not value:
                    raise HttpRequestParseError(
                        "Missing enc or value. Found enc=%s, value=%s", enc, value
                    )
                value = float(value)
            else:
                enc = encoding
            return enc, value

        raw_encodings = [part for part in encodings.split(",") if part]
        if len(raw_encodings) == 0:
            raise HttpRequestParseError("Empty values")

        parsed_encodings = {}  # encoding: value
        rejected_encodings = []
        pos = 0

        logger.debug(raw_encodings)
        while pos < len(raw_encodings):
            encoding = raw_encodings[pos]
            enc, qvalue = parse_encoding(encoding)
            if "*" == enc:
                # this is always at the end of content-coding
                if len(raw_encodings) - 1 != pos:
                    raise HttpRequestParseError(
                        f"Assumed '*' to be at the end. Found at {pos} split"
                    )
                if qvalue == 0:
                    rejected_encodings.append(
                        [
                            encoding
                            for encoding in acceptable_encodings
                            if encoding not in parsed_encodings.keys()
                        ]
                    )
                else:
                    parsed_encodings.update(
                        {
                            acceptable_encoding: qvalue
                            for acceptable_encoding in acceptable_encodings
                        }
                    )
                break
            else:
                if qvalue == 0:
                    rejected_encodings.append(enc)
                else:
                    parsed_encodings[enc] = max(qvalue, parsed_encodings.get(enc, 0))
            pos += 1

        # remove not acceptable encodings
        parsed_encodings = {
            key: value
            for key, value in parsed_encodings.items()
            if key not in rejected_encodings
        }
        # sort encodings based on qvalue
        parsed_encodings = OrderedDict(
            sorted(parsed_encodings.items(), key=lambda kv: kv[1], reverse=True)
        )

        if not all(
            [encoding in iana_registered_encodings for encoding in parsed_encodings]
        ):
            raise HttpRequestParseError(
                "Unknown encoding in %s. Allowed encodings: %s",
                parsed_encodings,
                iana_registered_encodings,
            )

        return list(parsed_encodings.keys())

    def parse_request(self, req):
        lines = req.splitlines()
        request_line = lines[0].decode("utf-8")

        self.method, self.path, self.http_version = request_line.rstrip("\r\n").split()

        self.headers = {}
        pos = 1
        while pos < len(lines):
            line = lines[pos].decode("utf-8")
            pos += 1
            if ":" not in line:
                break
            key, value = line.strip().replace(" ", "").split(":", 1)
            self.headers[key] = value

        data = "".join(line.decode("utf-8").strip() for line in lines[pos:])
        self.data = data.encode()

    def start_response(self, status, response_headers, exc_info=None):
        self.datetime = datetime.datetime.now(tz=datetime.timezone.utc).strftime(
            "%a, %d %b %Y %T GMT"
        )

        server_headers = [("Date", self.datetime), ("Server", f"whisky/{__version__}")]
        self.headers_set = [status, response_headers + server_headers]

        return lambda data: logger.warning(
            "Please do not use write() function.\n %s", data
        )

    def finish_response(self, result):
        self.status, response_headers = self.headers_set
        response = f"HTTP/1.1 {self.status}\r\n"
        for header in response_headers:
            response += "{0}: {1}\r\n".format(*header)

        message_body = "".join(data.decode("utf-8") for data in result)

        message_bytes = message_body.encode()

        for encoding in self.parsed_encodings:
            if encoding == "gzip":
                import gzip

                response += "Content-Encoding: gzip\r\n"
                message_bytes = gzip.compress(message_bytes)
                break
            elif encoding == "identity":
                # identity: same as without any encoding
                break
        else:
            raise Exception("Not expected to be here.")

        response += "Content-Length: {}\r\n".format(len(message_bytes))
        response += "\r\n"
        response_bytes = response.encode()

        response_bytes += message_bytes

        logger.debug("".join(f"> {line}\n" for line in response.splitlines()))
        self.request.sendall(response_bytes)


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
        try:
            self.finish_request(client_conn, client_address)
            self.shutdown_request(client_conn)
        except Exception as exc_info:
            logger.exception("Oops.", exc_info=exc_info)

    def process_request(self, client_conn, client_address):
        self.executor.submit(self.process_request_thread, client_conn, client_address)

    def finish_request(self, client_conn, client_address):
        self.request_handler_class(client_conn, client_address, self)

    def shutdown_request(self, client_conn):
        self.close_request(client_conn)

    def close_request(self, client_conn: socket.socket):
        client_conn.close()

    def handle_request(self, sock, mask):
        client_socket, client_address = self.listening_socket.accept()
        client_socket.settimeout(200)
        self.process_request(client_socket, client_address)

    def close_server(self):
        self._selector.unregister(self.listening_socket)
        self._selector.close()
        self.executor.shutdown(wait=True)
        self.listening_socket.close()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close_server()

    def __enter__(self):
        return self


def main():
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
    parser.add_argument(
        "-v",
        "--version",
        help="Version information",
        action="version",
        version=f"whisky/v{__version__}",
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


if __name__ == "__main__":
    main()
