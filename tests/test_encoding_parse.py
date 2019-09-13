from wsgi_server import WSGIRequestHandler, WSGIServer
from wsgi_server import acceptable_encodings
from collections import OrderedDict
import unittest

from wsgi_server import HttpRequestParseError


class EncodingParseTest(unittest.TestCase):
    def _test_different_encoding(self, actual, expected):
        parsed_encodings = WSGIRequestHandler.parse_encodings(actual)
        self.assertEqual(expected, parsed_encodings)

    def test_encodings(self):
        params = [
            {"actual": "*", "expected": acceptable_encodings},
            {"actual": "identity", "expected": ["identity"]},
            {"actual": "compress, gzip", "expected": ["compress", "gzip"]},
            {"actual": "identity;q=0", "expected": []},
            {"actual": "identity;q=0, gzip", "expected": ["gzip"]},
            {"actual": "identity;q=0, gzip;q=0.5", "expected": ["gzip"]},
            {
                "actual": "identity;q=0, gzip;q=0.5, deflate;q=0.8, *;q=1.0",
                "expected": ["gzip", "deflate"],
            },
            {"actual": "identity;q=0.5, gzip;q=1", "expected": ["gzip", "identity"]},
        ]
        for param in params:
            self._test_different_encoding(**param)

    def test_for_exceptions(self):
        def _test_raise_exception(actual, exception):
            with self.assertRaises(exception):
                value = WSGIRequestHandler.parse_encodings(actual)

        _test_raise_exception(actual=",", exception=HttpRequestParseError)
        _test_raise_exception(actual=";", exception=HttpRequestParseError)
        _test_raise_exception(actual="q", exception=HttpRequestParseError)
        _test_raise_exception(actual=";q", exception=HttpRequestParseError)
        _test_raise_exception(actual=";q=", exception=HttpRequestParseError)
        _test_raise_exception(actual="*;", exception=HttpRequestParseError)
        _test_raise_exception(actual="*;q", exception=HttpRequestParseError)
        _test_raise_exception(actual="*;q=", exception=HttpRequestParseError)
        _test_raise_exception(actual="*;q,", exception=HttpRequestParseError)


if __name__ == "__main__":
    runner = unittest.TestRunner()
    runner.run()
