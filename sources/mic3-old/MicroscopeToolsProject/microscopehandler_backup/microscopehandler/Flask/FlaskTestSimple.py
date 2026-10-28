from functools import wraps
from flask import Flask, make_response
from flask_cors import CORS, cross_origin
import imageio
import os, sys
import win32file
import datetime
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from CameraConnection import CameraConnection
mmc = CameraConnection()

app = Flask(__name__)
CORS(app)

def add_response_headers(headers={}):
    """This decorator adds the headers passed in to the response"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            resp = make_response(f(*args, **kwargs))
            h = resp.headers
            for header, value in headers.items():
                h[header] = value
            return resp
        return decorated_function
    return decorator

@app.route("/")
def hello():
    print("test")
    return "Hello World!"

@app.route('/LiveView')
def LiveView():
    with open("LiveView.html") as fp:
        return fp.read().replace("NAME", mmc.config["MicroscopeName"]).replace("Mic", "Microscope ")
    return app.send_static_file('LiveView.html')
    
@app.route('/favicon.ico')
def Favicon():
    with open("favicon.ico") as fp:
        return fp.read()
    return app.send_static_file('favicon.ico')

@app.route('/status.txt')
def Status():
    with open("status.txt") as fp:
        return fp.read()

@app.route('/percent.txt')
def Percent():
    if not mmc.getBlockingProcess():
        return "idle"
    with open("percent.txt") as fp:
        return fp.read()

@app.route('/disk.txt')
def Disk():
    secsPerClus, bytesPerSec, nFreeClus, totClus = win32file.GetDiskFreeSpace("D:\\")
    return "%d;%d" % (100-nFreeClus*100/totClus, secsPerClus*bytesPerSec*nFreeClus)

@app.route('/image.png')
@add_response_headers({'Content-Type': 'image/jpg'})
@add_response_headers({'Expires': datetime.datetime.utcnow() + datetime.timedelta(seconds=1)})
def Image():
    im = mmc.getLastImage()[::2, ::2]
    return imageio.imwrite(imageio.RETURN_BYTES, im, format=".jpg")

def KillOldServer():
    import win32api, psutil
    pid = win32api.GetCurrentProcessId()
    count = 0
    for process in psutil.process_iter():
        try:
            if process.name().find("python") != -1:
                script_name = os.path.split(process.cmdline()[-1])[1]
                if script_name == os.path.basename(__file__) and process.pid != pid:
                    for child in process.children(recursive=True):
                        child.kill()
                    process.kill()
                    count += 1
        except psutil.AccessDenied:
            pass
    return count

if __name__ == "__main__":
    while 1:
        try:
            os.chdir(os.path.dirname(__file__))
            KillOldServer()
            app.run(host='0.0.0.0',
                    port=5000)
        except Exception as err:
            print(err)
            pass
