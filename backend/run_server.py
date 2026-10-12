"""Local server entry point with a psycopg-compatible Windows event loop."""
import asyncio
import os
import sys

import uvicorn

from main import app


if __name__ == '__main__':
    loop = asyncio.SelectorEventLoop if sys.platform == 'win32' else 'auto'
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('SOLOVIBE_PORT', '8000')), loop=loop)
