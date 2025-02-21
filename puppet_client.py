import asyncio
import websockets
from websockets.asyncio.client import ClientConnection
import threading
import time
from typing import Optional, Any, Literal

from _config import ClientConfig
from _auth_msgs import auth_msg1, auth_msg2


info_names = Literal["server", "connection flag"] | Any



class PuppetClient:

    def __init__(self, config: ClientConfig) -> None:

        self.url = config.url
        self.version = config.v
        self.server = config.server
        self.login_str = config.login_str

        self.gather_timeout = 5
        self.max_queue_len = 1000

        self.request_queue: list[str] = []
        self.response_queue: list[str] = []
        
        self.index = 0
        self.search_index_offset = 0

        self.connection_closed = True

        self.allow_new_requests = threading.Event()
        self.allow_new_requests.set()

        self.connection_task: asyncio.Task | None = None
        self.reconnect_flag = asyncio.Event()


    async def connect(self) -> None:
        self.reconnect_flag.set()
        if self.connection_task is None:
            self.connection_task = asyncio.create_task(
                self._connect()
            )


    async def disconnect(self) -> None:
        self.reconnect_flag.clear()


    async def toggle_connection(self) -> None:
        if self.reconnect_flag.is_set():
            await self.disconnect()
        else:
            await self.connect()


    async def send_request(
        self, 
        message: str
    ) -> list[str] | None:
        
        # Ensures only 1 request is sent at once
        self.allow_new_requests.wait()
        self.allow_new_requests.clear()

        response_format = await self._predict_response_format(message)
        if response_format is None:
            return
        
        self.request_queue.append(message)

        response_list = await self._gather_responses(
            response_format,
            timeout=self.gather_timeout
        )

        self.allow_new_requests.set()
        return response_list
    

    async def search_responses(
        self,
        start_index: int,
        response_format: str
    ) -> list[list[str] | int]:
        
        result, end_index = await self._search_responses(
            start_index,
            response_format
        )
        return [result, end_index]
    

    async def get_info(self, name: info_names) -> Any:
        if name == "server":
            return self.server
        if name == "connection flag":
            # returns true if connection is allowed
            return self.reconnect_flag.is_set()


    async def _connect(self) -> None:
        while True:
            await self._init_connection()

            await self.reconnect_flag.wait()
            await asyncio.sleep(5)


    async def _init_connection(self) -> None:
        try:
            self.connection_closed = False
            async with websockets.connect(
                self.url, ping_interval=5
            ) as websocket:
                
                print(f"Initiating connection with {self.url}")

                receiver_task = asyncio.create_task(
                    self._receive_data_loop(websocket)
                )
                # Authentication
                await websocket.send(auth_msg1(self.version))
                await websocket.send(auth_msg2(self.server))
                await websocket.send(self.login_str)

                msg_loop_task = asyncio.create_task(
                    self._send_msg_loop(websocket)
                )

                await receiver_task

        except Exception as e:
            print("Error in _init_connection", e)

        self.connection_closed = True
        return


    async def _send_msg_loop(
        self,
        websocket: ClientConnection
    ) -> None:
        
        message = ""
        try:
            while True:
                if len(self.request_queue) > 0:
                    message = self.request_queue.pop(0)
                    await websocket.send(message)

                if self.connection_closed:
                    return
                
                await asyncio.sleep(0.1)

        except websockets.ConnectionClosed:
            self.request_queue.insert(0, message)

        except Exception as e:
            self.request_queue.insert(0, message)
            print("Error in _send_msg_loop", e)


    async def _receive_data_loop(
        self, 
        websocket: ClientConnection
    ) -> None:
        
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    str_message = message.decode()
                elif isinstance(message, bytearray):
                    str_message = bytes(message).decode()
                elif isinstance(message, memoryview):
                    str_message = message.tobytes().decode()
                else:
                    str_message = message

                self.response_queue.append(str_message)
                await self._response_queue_resize()

                if not self.reconnect_flag.is_set():
                    return

                await asyncio.sleep(0.1)

        except websockets.ConnectionClosed:
            return
        
        except Exception as e:
            print("Error in _receive_data_loop", e)


    async def _response_queue_resize(self) -> None:
        extra = len(self.response_queue) - self.max_queue_len
        if extra > 0:
            self.response_queue = self.response_queue[extra:]
            self.index -= extra
            self.search_index_offset -= extra


    async def _predict_response_format(
        self, 
        message: str
    ) -> list[str] | None:
        
        """Predicts the format of response from server"""
        response_format = []

        if message.startswith(f"%xt%{self.server}%gaa"):
            response_format = ["%xt%gaa"] # map data
        else:
            return
        
        return response_format
    

    async def _gather_responses(
        self,
        response_format: list[str],
        timeout: float
    ) -> list[str]:
        
        """Gathers all expected response"""
        # "response format" contains prefixes of expected responses

        start_time = time.time()
        gather_count = 0
        response_list = []

        # Ensures it doesn't gather previous responses
        self.index = len(self.response_queue)

        while gather_count < len(response_format):
            await asyncio.sleep(0.1)

            # Timeout
            if time.time() - start_time > timeout:
                break

            if len(self.response_queue) <= self.index:
                continue

            response = self.response_queue[self.index]
            if response.startswith(response_format[gather_count]):
                response_list.append(response)
                gather_count += 1

            self.index += 1

        return response_list


    async def _search_responses(
        self,
        start_index: int,
        response_format: str
    ) -> tuple[list[str], int]:
        
        """Find all responses with a specific prefix after an index"""
        
        result = []

        index = max(start_index + self.search_index_offset, 0)
        while index < len(self.response_queue):
            respose = self.response_queue[index]
            if respose.startswith(response_format):
                result.append(respose)

            index += 1

        end_index = len(self.response_queue) - self.search_index_offset
        return result, end_index
    


class Manager:

    def __init__(self) -> None:
        self.puppet_clients: list[PuppetClient] = []


    def new_client(self, config: ClientConfig) -> None:
        self.puppet_clients.append(PuppetClient(config))


    async def connect(self, index: Optional[int] = None) -> None:
        if index is None:
            for puppet_client in self.puppet_clients:
                await puppet_client.connect()
        
        elif index < len(self.puppet_clients):
            await self.puppet_clients[index].connect()


    async def disconnect(self, index: Optional[int] = None) -> None:
        if index is None:
            for puppet_client in self.puppet_clients:
                await puppet_client.disconnect()
        
        elif index < len(self.puppet_clients):
            await self.puppet_clients[index].disconnect()


    async def toggle_connection(
        self, 
        index: Optional[int] = None
    ) -> list[bool]:
        
        if index is None:
            for puppet_client in self.puppet_clients:
                await puppet_client.toggle_connection()
        
        elif index < len(self.puppet_clients):
            await self.puppet_clients[index].toggle_connection()

        return [
            await self.get_info(i, name="connection flag")
            for i in range(len(self.puppet_clients))
        ]


    async def send_request(
        self, 
        client_index: int,
        *,
        message: str
    ) -> list[str] |  None:
        
        if client_index >= len(self.puppet_clients):
            return
        
        puppet_client = self.puppet_clients[client_index]
        return await puppet_client.send_request(message)


    async def search_responses(
        self,
        client_index: int,
        *,
        start_index: int,
        response_format: str
    ) -> list[list[str] | int]:

        if client_index >= len(self.puppet_clients):
            return [[], 0]
        
        puppet_client = self.puppet_clients[client_index]
        search_results =  await puppet_client.search_responses(
            start_index, 
            response_format
        )
        return search_results
    

    async def get_info(
        self, 
        client_index: int,
        *,
        name: info_names
    ) -> Any:
        
        if client_index >= len(self.puppet_clients):
            return
        
        puppet_client = self.puppet_clients[client_index]
        return await puppet_client.get_info(name)