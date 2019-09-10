## Whisky
Multithreaded, WSGI-compatible web server with zero dependencies. *Just for Fun*.

Work In Progress.

## Installation
    $ pip install git+https://github.com/skshetry/whisky.git

## Usage:
    $ whisky [OPTIONS] MODULE_NAME:VARIABLE_NAME

The module name can be a full dotted path. The variable name refers to a WSGI
callable/application that should be found in the specified module.

### Example with bundled app
1. Clone this repo, and go to root folder of this repo
    (Assuming already installed, otherwise check [installation](#Installation)).
2. Run following command in shell:

        $ whisky wsgi_app:application

Open up http://localhost:8000. If it works, you are good to go.

### Available Options:

    usage: whisky [-h] [-d] [-b BIND] [-p PORT] [--workers WORKERS] application

    positional arguments:
        application           wsgi application in the form module:callable,
                              eg: wsgi_app:application

    optional arguments:
        -h, --help            show this help message and exit
        -d, --debug           Enable debug mode
        -b BIND, --bind BIND  Specify alternate bind address
        -p PORT, --port PORT  Specify alternate port [default: 8000]
        --workers WORKERS     No. of threads to handle requests

## Development
1. Clone this repo.
2. Edit code.
3. Run `./wsgi_server.py MODULE_NAME:VARIABLE_NAME -d` to run.

    You can also use test app bundled with the server.
    Eg: `./wsgi_server.py wsgi_app:application -d`

Currently, the server is tested with the bundled app and `flaskr` app, and is compared
with `wsgiref` as reference.