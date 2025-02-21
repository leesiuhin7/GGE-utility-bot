from flask import Flask, request, abort, jsonify, Response
from asgiref.wsgi import WsgiToAsgi
import asyncio
import os
import uvicorn
import pyotp

from puppet_client import Manager
from _config import get_config


totp = pyotp.TOTP(os.environ.get("KEY", ""))
puppet_manager = Manager()
app = Flask(__name__)


@app.route("/send", methods=["POST"])
async def request_send_msg() -> Response:
    if not request.is_json:
        abort(415)

    data = request.get_json()

    client_index = data.get("client_index")
    message = data.get("message")

    if client_index is None:
        abort(400)
    elif message is None:
        abort(400)

    response = await puppet_manager.send_request(
        client_index,
        message=message
    )
    if response is None:
        abort(403)

    json_response = jsonify(response)
    return json_response


@app.route("/search", methods=["POST"])
async def request_search_response() -> Response:
    if not request.is_json:
        abort(415)

    data = request.get_json()

    client_index = data.get("client_index")
    start_index = data.get("index")
    response_format = data.get("format")

    if not isinstance(client_index, int):
        abort(400)
    elif not isinstance(start_index, int):
        abort(400)
    elif not isinstance(response_format, str):
        abort(400)

    response = await puppet_manager.search_responses(
        client_index,
        start_index=start_index,
        response_format=response_format
    )
    json_response = jsonify(response)

    return json_response


@app.route("/get", methods=["POST"])
async def request_get_info() -> Response:
    if not request.is_json:
        abort(415)

    data = request.get_json()

    client_index = data.get("client_index")
    name = data.get("name")

    if not isinstance(client_index, int):
        abort(400)
    elif not isinstance(name, str):
        abort(400)

    response = await puppet_manager.get_info(
        client_index, 
        name=name
    )
    json_response = jsonify(response)

    return json_response


@app.route("/control", methods=["POST"])
async def toggle_connection() -> Response:
    if not request.is_json:
        abort(415)

    data = request.get_json()
    otp = data.get("otp")

    real_otp = await asyncio.to_thread(totp.now)
    if otp != real_otp:
        return abort(401)
    
    response = await puppet_manager.toggle_connection()
    json_response = jsonify(response)
    
    return json_response
    



async def main() -> None:
    for client_config in get_config():
        puppet_manager.new_client(client_config)

    await puppet_manager.connect()

    asgi_app = WsgiToAsgi(app)
    port = int(os.environ.get("PORT", 10000))

    config = uvicorn.Config(asgi_app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    await server.serve()

    print("Server process terminated.")



if __name__ == "__main__":
    asyncio.run(main())