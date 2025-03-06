import httpx
import asyncio
import logging
from typing import Any, Self

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
        logging.exception(f"An error occured: {e}")
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
                logging.exception(f"An error occured: {e}")
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
                logging.exception(f"An error occured: {e}")
                continue

            for message in message_list:
                try:
                    info_list = dp.attack_warning.decode_message(
                        message
                    )
                
                except IndexError:
                    continue
                
                except Exception as e:
                    logging.exception(f"An error occured: {e}")
                    continue

                if info_list is None:
                    continue

                for info in info_list:
                    if info[7] in self.prev_atk_ids[client_index]:
                        continue
                    else:
                        self.prev_atk_ids[client_index].append(info[7])

                    warning_msg = dp.attack_warning.format_warning(info)
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
                if info[2] in self.criterias:
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
        response = await post(self.url, data)

        if response is None:
            return []
        
        try:
            response_list = response.json()
        except Exception as e:
            logging.exception(f"An error occured: {e}")
            return []
        
        try:
            storm_fort_list = dp.storm_fort.decode_message(
                response_list[0]
            )
        except IndexError:
            return []
        except Exception as e:
            logging.exception(f"An error occured: {e}")
            return []

        if storm_fort_list is None:
            return []
        
        return storm_fort_list