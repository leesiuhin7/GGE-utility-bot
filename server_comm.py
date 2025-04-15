import httpx
import asyncio
import logging
import websockets
from websockets.asyncio.client import ClientConnection
import json
from typing import Any, Self, Optional

import data_process as dp



async def post(
    url: str, 
    data: Any,
    **kwargs
) -> httpx.Response | None:
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, **kwargs)
            return response
        
    except httpx.RequestError:
        return
    
    except Exception as e:
        logging.exception(f"An error occurred: {e}")
        return
    

class WSComm:

    def __init__(self, url: str) -> None:
        self.url = url

        self.reconnect_cooldown = 10

        self.connection_closed = True

        self._input_queue = asyncio.Queue()
        self._retry_input_queue = asyncio.Queue()
        self._waiters: dict[int, asyncio.Event] = {}

        self._recv_queue = asyncio.Queue()
        self._responses: dict[int, Any] = {}

        self.connection_task: asyncio.Task | None = None
        self.response_task: asyncio.Task | None = None


    class NoResponse(Exception):
        """Raised if the server failed to respond to a request"""
        pass


    async def request(
        self, 
        method: str, 
        input_data: Any,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Sends a request to the server, waits until a response
        is received or timeout

        :raises NoResponse: If no response is received before timeout
        :return: Returns the content of the response
        :rtype: Any
        """
        waiter, request_id = self._register()

        request_dict = {
            "id": request_id,
            "method": method,
            "data": input_data
        }
        request = json.dumps(request_dict)
        
        # Send request and wait for response
        await self._input_queue.put(request)
        waiting_task = asyncio.create_task(waiter.wait())
        done, pending = await asyncio.wait(
            [waiting_task], 
            timeout=timeout
        )

        if request_id not in self._responses:
            raise WSComm.NoResponse
        else:
            return self._responses[request_id]
        

    async def start(self) -> None:
        if self.connection_task is None:
            self.connection_task = asyncio.create_task(
                self._connection_loop()
            )

        if self.response_task is None:
            self.response_task = asyncio.create_task(
                self._process_response_loop()
            )
        

    async def _connection_loop(self) -> None:
        request = None
        async for websocket in websockets.connect(self.url):
            logging.info(f"Initiating connection with {self.url}")

            self.connection_closed = False

            try:
                receiver_task = asyncio.create_task(
                    self._receive_loop(websocket)
                )

                # Send message loop
                while True:
                    request = await self._get_next_request()
                    await websocket.send(request)
                    request = None

            except websockets.ConnectionClosed:
                pass

            except Exception as e:
                logging.exception(f"An error occurred: {e}")
                pass

            logging.info(f"Connection closed with {self.url}")

            self.connection_closed = True
            
            # Retry logic
            if request is not None:
                await self._retry_input_queue.put(request)

            await asyncio.sleep(self.reconnect_cooldown)
        

    async def _receive_loop(
        self,
        websocket: ClientConnection
    ) -> None:
        
        try:
            async for message in websocket:
                await self._recv_queue.put(message)

        except websockets.ConnectionClosed:
            pass

        except Exception as e:
            logging.exception(f"An error occurred: {e}")


    async def _process_response_loop(self) -> None:
        while True:
            response = await self._recv_queue.get()
            unpacked = self._unpack_response(response)
            if unpacked is None:
                continue

            content, response_id = unpacked

            # Shares the content of the response
            self._responses[response_id] = content
            self._release(response_id)


    async def _get_next_request(self) -> Any:
        if self._retry_input_queue.empty():
            return await self._input_queue.get()
        else:
            return await self._retry_input_queue.get()


    def _unpack_response(
        self, 
        response: str | bytes | bytearray
    ) -> tuple[Any, int] | None:
        
        try:
            data = json.loads(response)
        except Exception as e:
            return
        
        if not isinstance(data, dict):
            return
        
        content = data.get("content")
        response_id = data.get("id")

        if not isinstance(response_id, int):
            return
        
        return content, response_id


    def _register(self) -> tuple[asyncio.Event, int]:
        """
        Registers an asyncio.Event instance (waiter) to an unique id

        :return: A tuple of the waiter and its id
        :rtype: tuple[asyncio.Event, int]
        """
        used_ids = set(self._waiters.keys())
        request_id = 0
        while request_id in used_ids:
            request_id += 1

        # Register an asyncio.Event to the id
        waiter = asyncio.Event()
        self._waiters[request_id] = waiter
        return waiter, request_id
    

    def _release(self, waiter_id: int) -> None:
        """
        Removes an asyncio.Event instance (waiter) 
        with a specific id and sets it

        :param waiter_id: The id of the waiter
        :type waiter_id: int
        """
        if waiter_id in self._waiters:
            waiter = self._waiters.pop(waiter_id)
            waiter.set()
    


class Info:
    servers: list[str] = []
    url: str = ""
    client_count: int = 0

    ws_comm: WSComm

    @classmethod
    async def bind(cls, url: str, count: int) -> None:
        cls.url = url
        cls.client_count = count

        for i in range(count):
            data = {
                "client_index": i,
                "name": "server"
            }
            response = await post(f"{url}/get", data=data)
            if response is None:
                raise Exception("Unable to connect to server.")

            try:
                server = response.json()
            except Exception as e:
                logging.exception(f"An error occurred: {e}")
                continue

            if server is not None:
                cls.servers.append(server)


    @classmethod
    def ws_bind(cls, ws_comm: WSComm) -> None:
        cls.ws_comm = ws_comm



class AttackListener:

    def __init__(self, output: asyncio.Queue) -> None:
        self.output = output
        self.cancel_flag = False

        self.update()


    def update(self) -> None:
        self.url = f"{Info.url}/search"
        self.count = Info.client_count

        self.prev_atk_ids = [[] for _ in range(self.count)]


    async def attack_listener(
        self,
        client_index: int, 
        interval: float = 15
    ) -> None:
        
        index = 10 ** 10
        while not self.cancel_flag:
            await asyncio.sleep(interval)

            data = {
                "client_index": client_index,
                "index": index,
                "format": "%xt%gam"
            }

            try:
                response = await Info.ws_comm.request(
                    "search", data, timeout=10
                )
            except WSComm.NoResponse:
                continue
            except Exception as e:
                logging.exception(f"An error occurred: {e}")
                continue

            try:
                message_list, index = json.loads(response)
            except Exception as e:
                logging.exception(f"An error occurred: {e}")
                continue

            for message in message_list:
                await self.process_message(message, client_index)


    async def start(self) -> None:
        listeners = [
            self.attack_listener(i) 
            for i in range(self.count)
        ]
        self.listener_tasks = asyncio.gather(*listeners)
    

    async def cancel(self, blocking: bool = True) -> None:
        self.cancel_flag = True
        if blocking:
            await self.listener_tasks


    async def process_message(
        self, 
        message: Any,
        client_index: int
    ) -> None:
        
        try:
            info_list = dp.attack_warning.decode_message(
                message
            )
        except IndexError:
            return
        except Exception as e:
            logging.exception(f"An error occurred: {e}")
            return

        if info_list is None:
            return

        for info in info_list:
            if info[7] in self.prev_atk_ids[client_index]:
                continue
            elif info[6] == "": # is event attack
                continue
            else:
                self.prev_atk_ids[client_index].append(info[7])

            warning_msg = dp.attack_warning.format_warning(info)
            await self.output.put((warning_msg, client_index))



class StormFort:

    def __init__(self) -> None:
        self.update()


    def update(self) -> None:
        self.servers = Info.servers.copy()
        self.url = f"{Info.url}/send"


    class _Searcher:
        
        def __init__(
            self,
            *, 
            storm_fort: "StormFort",
            client_index: int,
            center_x: int,
            center_y: int,
            end: int,
            criterias: list[int]
        ) -> None:
            
            self.current = 0
            self.end = end

            self.storm_fort = storm_fort

            self.client_index = client_index
            self.center_x = center_x
            self.center_y = center_y
            self.criterias = criterias


        def __aiter__(self) -> Self:
            return self
        

        async def __anext__(self) -> list[str]:
            if self.current >= self.end:
                raise StopAsyncIteration
            
            self.current += 1
            
            offsets = await self.storm_fort._generate_offsets(
                self.current + 1
            )
            storm_fort_list: list[tuple[int, int, int]] = []
            for offset in offsets:
                i, j = offset[0] - 0.5, offset[1] - 0.5
                x = int(self.center_x + i * 13)
                y = int(self.center_y + j * 13)
                bbox = (x, y, x + 12, y + 12)

                storm_fort_list.extend(
                    await self.storm_fort._get_storm_fort_data(
                        self.client_index,
                        bbox=bbox
                    )
                )

            selected = []
            for info in storm_fort_list:
                if info in selected:
                    pass # Ignore info since it's repeated
                elif info[2] in self.criterias:
                    selected.append(info)

            sorted_list = dp.storm_fort.sort_storm_forts(
                selected,
                (self.center_x, self.center_y)
            )
            text = dp.storm_fort.format_storm_forts(
                sorted_list, 
                max_lines=40
            )
            return text


    async def search(
        self, 
        client_index: int,
        center: str,
        dist: int,
        criterias: list[str]
    ) -> "_Searcher | None":
        
        """
        Returns an async iterator that searches storm forts 
        per iteration

        :return: An async iterator that searches for storm forts
        or None if input data is invalid
        :rtype: StormFort._Searcher | None
        """
        
        new_criterias = dp.storm_fort.translate_criterias(criterias)

        coords = center.split(":")
        if len(coords) != 2:
            return None
        
        try:
            center_x = int(coords[0])
            center_y = int(coords[1])
        except ValueError:
            return None
        except Exception as e:
            return None
        
        n = - (dist // -13) # celiing division
        if n <= 0:
            return None
        
        return StormFort._Searcher(
            storm_fort=self,
            client_index=client_index,
            center_x=center_x,
            center_y=center_y,
            end=n,
            criterias=new_criterias
        )
    

    async def _generate_offsets(
        self, 
        n: int
    ) -> list[tuple[float, float]]:
        """
        In a (2n) by (2n) grid centered at (0, 0) 
        made of 1x1 squares, 
        return the center positions of all outermost squares

        :param n: Half of the length of a (2n) by (2n) grid
        :type n: int
        :return: A list of center positions of all outermost squares
        :rtype: list[tuple[float, float]
        """

        # Generates the top-right side of the grid
        base = []
        for x in range(0, n):
            base.append((x + 0.5, n - 0.5))

        for y in range(1, n):
            base.append((n - 0.5, y + 0.5))

        # Generates the entire grid (output) by mirroring
        offsets = []
        for base_offset in base:
            for i, j in [
                (-1, -1), (-1, 1), (1, -1), (1, 1)
            ]:
                offsets.append((
                    base_offset[0] * i,
                    base_offset[1] * j
                ))

        return offsets


    async def _get_storm_fort_data(
        self,
        client_index: int,
        bbox: tuple[int, int, int, int]
    ) -> list[tuple[int, int, int]]:
        
        if client_index >= len(self.servers):
            return []
        
        server = self.servers[client_index]

        x1, y1, x2, y2 = bbox
        message = (
            f"%xt%{server}%gaa%1%"
            "{"
            f'"KID":4,"AX1":{x1},"AY1":{y1},"AX2":{x2},"AY2":{y2}'
            "}%"
        )

        data = {
            "client_index": client_index,
            "message": message
        }
        try:
            response = await Info.ws_comm.request(
                "send", data, timeout=10
            )
        except WSComm.NoResponse:
            return []
        except Exception as e:
            logging.exception(f"An error occurred: {e}")
            return []
        
        try:
            response_list = json.loads(response)
        except Exception as e:
            logging.exception(f"An error occurred: {e}")
            return []
        
        try:
            storm_fort_list = dp.storm_fort.decode_message(
                response_list[0]
            )
        except IndexError:
            return []
        except Exception as e:
            logging.exception(f"An error occurred: {e}")
            return []

        if storm_fort_list is None:
            return []
        
        return storm_fort_list