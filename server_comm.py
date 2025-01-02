import httpx
import asyncio
from typing import Any

from data_process import *



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
        print("Error when sending post request", e)
        return
    


class Info:
    servers: list[str] = []
    url: str = ""
    client_count: int = 0

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
                print("Error while decoding server info", e)
                continue

            if server is not None:
                cls.servers.append(server)



class AttackListener:

    def __init__(self, output: list) -> None:
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
            response = await post(self.url, data, timeout=10)

            if response is None:
                continue

            try:
                message_list, index = response.json()
            except Exception as e:
                print("Error in attack listener while unpacking", e)
                continue

            for message in message_list:
                try:
                    info_list = attack_warning.decode_message(message)
                
                except IndexError:
                    continue
                
                except Exception as e:
                    print("Error in attack listener while decoding", e)
                    continue

                if info_list is None:
                    continue

                for info in info_list:
                    if info[7] in self.prev_atk_ids[client_index]:
                        continue
                    else:
                        self.prev_atk_ids[client_index].append(info[7])

                    warning_msg = attack_warning.format_warning(info)
                    self.output.append((warning_msg, client_index))


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



class StormFort:

    def __init__(self) -> None:
        self.update()


    def update(self) -> None:
        self.servers = Info.servers.copy()
        self.url = f"{Info.url}/send"


    async def search(
        self, 
        client_index: int, 
        center: str,
        dist: int,
        criterias: list[str]
    ) -> list[str]:
        
        new_criterias = storm_fort.translate_criterias(criterias)

        coords = center.split(":")
        if len(coords) != 2:
            return []
        else:
            x = int(coords[0])
            y = int(coords[1])

        bbox = (x - dist, y - dist, x + dist, y + dist)

        storm_fort_list = await self._get_storm_fort_data(
            client_index,
            bbox=bbox
        )

        selected_storm_forts = []

        for storm_fort_info in storm_fort_list:
            if storm_fort_info[2] in new_criterias:
                selected_storm_forts.append(storm_fort_info)

        text = storm_fort.format_storm_forts(selected_storm_forts, 40)
        return text



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
        response = await post(self.url, data)
        print(response)

        if response is None:
            return []
        
        try:
            response_list = response.json()
        except Exception as e:
            print("Error in storm fort while decoding json", e)
            return []
        
        try:
            storm_fort_list = storm_fort.decode_message(
                response_list[0]
            )
        except IndexError:
            return []
        except Exception as e:
            print("Error in storm fort while decoding message", e)
            return []

        if storm_fort_list is None:
            return []
        
        return storm_fort_list