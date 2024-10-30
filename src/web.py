from flask import Flask, render_template, request

import pytest

app = Flask(__name__)

@app.route("/self-consumption", methods=['GET'])
def self_consumption():
    res = pytest.main(["./self_consumption.py"])
    if res == 0:
        message = "Success"
        response = 200
    else:
        message = "Fail"
        response = 500
    return message, response


@app.route("/full-backup", methods=['GET'])
def full_backup():
    res = pytest.main(["./full_backup.py"])
    if res == 0:
        message = "Success"
        response = 200
    else:
        message = "Fail"
        response = 500
    return message, response


if __name__ == "__main__":
   app.run(host='0.0.0.0', port=8080, debug=False)