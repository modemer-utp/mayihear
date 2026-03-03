import os
import sys

os.environ.setdefault('GEMINI_API_KEY', '__GEMINI_API_KEY_PLACEHOLDER__')

if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)

data_dir = os.environ.get('MAYIHEAR_DATA_DIR')
if data_dir:
    os.makedirs(data_dir, exist_ok=True)

import uvicorn

if __name__ == '__main__':
    uvicorn.run('api.main:app', host='127.0.0.1', port=8000, log_level='info')
