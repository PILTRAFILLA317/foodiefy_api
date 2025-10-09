from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/api/data', methods=['GET'])
def get_data():
    response = {
        "message": "Hello from Flask!",
        "data": {
            "key1": "value1",
            "key2": "value2"
        }
    }
    return jsonify(response)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)