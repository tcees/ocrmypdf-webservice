import os
##
# REDIS SETUP
from redis import Redis 
rediscli = Redis(host=os.environ['REDIS_HOST'], port=os.environ['REDIS_PORT'], password=os.environ['REDIS_PASSWORD'])

##
# LOGGING SETUP
import json
import re
from logging import StreamHandler

class MyLogHandler(StreamHandler):
    def __init__(self, filename, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filename = filename

    def extract_page(self, text):
        m = re.search(r'(?<=Rotations for page )\d+', text)
        return m.group(0)

    def emit(self, record):
        msg = self.format(record)
        print('{} - {}'.format(self.filename, msg))
        if 'Rotations for page' in msg:
            page = int(self.extract_page(msg)) + 1
            message = json.dumps({ 'filename': self.filename, 'page': page })
            rediscli.publish(os.environ['REDIS_CHANNEL'], message)

##
# OCRizer
import ocrmypdf

def do_myocr(filename, up_file, down_file):
    logger = ocrmypdf.configure_logging(-1)
    mh = MyLogHandler(filename)
    logger.addHandler(mh)    
    ocrmypdf.ocr(up_file, down_file, progress_bar=False, skip_text=True)
##
# WEBSERVICE

import shlex
from subprocess import PIPE, run
from tempfile import TemporaryDirectory

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    request,
    send_from_directory,
    url_for,
)
from flask_cors import CORS, cross_origin
from multiprocessing import Process

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'
app.secret_key = "secret"
app.config['MAX_CONTENT_LENGTH'] = 50_000_000
app.config.from_envvar("OCRMYPDF_WEBSERVICE_SETTINGS", silent=True)

ALLOWED_EXTENSIONS = set(["pdf"])

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def do_ocrmypdf(filename, filepath):
    downloaddir = TemporaryDirectory(prefix="ocrmypdf-download")
    down_file = os.path.join(downloaddir.name, filename)
	
    params = ""
    if ("params" in request.form):
        params = request.form["params"]
    cmd_args = [arg for arg in shlex.split(params)]
	
    if "--sidecar" in cmd_args:
        return Response("--sidecar not supported", 501, mimetype='text/plain')
    
    p = Process(target=do_myocr, args=(filename, filepath, down_file, ))
    p.start()
    p.join()
	
    message = json.dumps({ 'filename': filename, 'page': -1 })
    rediscli.publish(os.environ['REDIS_CHANNEL'], message)
    return send_from_directory(downloaddir.name, filename, as_attachment=True)

from urllib.parse import unquote

@app.route("/", methods=["GET", "POST"])
@cross_origin()
def upload_file():
    if request.method == "POST":
        if "file" not in request.files:
            return Response("Missing file", 400, mimetype='text/plain')
        file = request.files["file"]
        uploaddir = TemporaryDirectory(prefix="ocrmypdf-upload")
        filepath = os.path.join(uploaddir.name, file.filename)
        file.save(filepath)
        
        if filepath == "":
            return Response("Empty filepath", 400, mimetype='text/plain')
		
        if not allowed_file(file.filename):
            return Response("Invalid filename", 400, mimetype='text/plain')
        if allowed_file(file.filename):
            return do_ocrmypdf(file.filename, filepath)
    		
        return Response("Some other problem", 400, mimetype='text/plain')
    return """
    <!doctype html>
    <title>OCRmyPDF webservice</title>
    <h1>Upload a PDF (debug UI)</h1>
    <form method=post enctype=multipart/form-data>
      <label for="args">Command line parameters</label>
      <input type=textbox name=params>
      <label for="file">File to upload</label>
      <input type=file name=file>
      <input type=submit value=Upload>
    </form>
    <h4>Notice</h2>
    <div style="font-size: 70%; max-width: 34em;">
    <p>This is a webservice wrapper for OCRmyPDF.</p>
    <p>Copyright 2019 James R. Barlow</p>
    <p>This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    </p>
    <p>This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    </p>
    <p>
    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see &lt;http://www.gnu.org/licenses/&gt;.
    </p>
    </div>
    """

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=os.environ['WEBSERVICE_PORT'], debug=os.environ['DEBUG_MODE'] == 'True')